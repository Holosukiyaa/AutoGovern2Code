from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .errors import GIT_MISSING, AG2CError
from .util import hidden_process_kwargs

_GIT_NAMES = ("git.exe", "git")
_BUNDLED_GIT_BIN_RELATIVE = ("cmd", "mingw64/bin", "usr/bin", "bin")
GIT_SOURCE_SYSTEM = "system"
GIT_SOURCE_BUNDLED = "bundled"
GIT_SOURCE_CONFIG_KEY = "ag2c.git-source"
MINGIT_VERSION = "2.55.0.5"
MINGIT_TAG = "v2.55.0.windows.5"
MINGIT_ZIP_NAME = f"MinGit-{MINGIT_VERSION}-64-bit.zip"
MINGIT_URL = f"https://github.com/git-for-windows/git/releases/download/{MINGIT_TAG}/{MINGIT_ZIP_NAME}"
MINGIT_SHA256 = "56d7b226b7693196cfc71fef26568f536c4a021ab6c37ff2db4287bed908e96e"
_MISSING_GIT = (
    "Git is not available. Install Git and keep it on PATH, "
    "or let AG2C download a bundled Git for Windows."
)
_MISSING_GIT_UNIX = "Git is not available. Install Git and keep it on PATH."


def bundled_git_root() -> Path | None:
    for root in _candidate_bundled_roots():
        if _git_exe_in(root):
            return root
    return None


_SYSTEM_GIT_CACHE: dict[str, str | None] = {}


def system_git_executable() -> str | None:
    # Scanning PATH costs hundreds of milliseconds on Windows (thousands of
    # file probes per call), and the resolution cannot change unless PATH
    # itself changes, so memoize per PATH value.
    path_value = os.environ.get("PATH") or ""
    if path_value in _SYSTEM_GIT_CACHE:
        return _SYSTEM_GIT_CACHE[path_value]
    resolved = _scan_system_git()
    _SYSTEM_GIT_CACHE[path_value] = resolved
    return resolved


def _scan_system_git() -> str | None:
    for name in ("git.exe", "git"):
        found = shutil.which(name)
        if not found:
            continue
        path = Path(found)
        if path.suffix.lower() in {".cmd", ".bat"}:
            sibling = path.with_suffix(".exe")
            if sibling.is_file():
                return str(sibling.resolve())
            continue
        return str(path.resolve())
    return None


_PERSISTED_GIT_SOURCE: set[str] = set()


def git_executable(root: Path | None = None) -> str:
    override = os.environ.get("AG2C_GIT", "").strip()
    if override:
        path = Path(override).expanduser()
        if path.is_file():
            return str(path.resolve())
        raise AG2CError(_MISSING_GIT, code=GIT_MISSING)
    shipped = shipped_git_executable()
    if shipped:
        return shipped
    bundled = _git_exe_in(bundled_git_root())
    if bundled:
        return bundled
    source = read_local_git_source(root) if root is not None else ""
    if source == GIT_SOURCE_BUNDLED:
        try:
            return ensure_bundled_git()
        except AG2CError:
            system = system_git_executable()
            if system:
                return system
            raise
    system = system_git_executable()
    if system:
        return system
    return ensure_bundled_git()


def _run_git(
    executable: str,
    root: Path,
    *args: str,
    check: bool = True,
    binary: bool = False,
    stdin: bytes | str | None = None,
    env: dict[str, str] | None = None,
) -> str | bytes:
    resolved_root = root.expanduser().resolve()
    run_env = git_command_env(executable=executable)
    if env:
        run_env.update(env)
        run_env = git_command_env(run_env, executable=executable)
    try:
        completed = subprocess.run(
            [executable, "-c", f"safe.directory={resolved_root}", "-C", str(resolved_root), *args],
            check=False,
            capture_output=True,
            text=not binary,
            encoding=None if binary else "utf-8",
            errors=None if binary else "replace",
            input=stdin,
            env=run_env,
            shell=False,
            **hidden_process_kwargs(),
        )
    except FileNotFoundError as exc:
        raise AG2CError(_MISSING_GIT, code=GIT_MISSING) from exc
    except OSError as exc:
        raise AG2CError(f"cannot execute Git: {exc}") from exc
    if check and completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace") if binary else completed.stderr
        raise AG2CError(f"Git command failed ({' '.join(args)}): {str(stderr).strip()}")
    return completed.stdout


def git(
    root: Path,
    *args: str,
    check: bool = True,
    binary: bool = False,
    stdin: bytes | str | None = None,
    env: dict[str, str] | None = None,
) -> str | bytes:
    resolved_root = root.expanduser().resolve()
    executable = git_executable(resolved_root)
    output = _run_git(
        executable,
        resolved_root,
        *args,
        check=check,
        binary=binary,
        stdin=stdin,
        env=env,
    )
    marker = str(resolved_root)
    if marker not in _PERSISTED_GIT_SOURCE:
        _persist_git_source(resolved_root, executable)
        _PERSISTED_GIT_SOURCE.add(marker)
    return output


# A path's toplevel never changes within a process, and management code asks for
# the same root many times per snapshot (activation, manifest, tasks, status...).
# Only successes are cached: a directory that becomes a repo later must still work.
_REPO_ROOT_CACHE: dict[str, Path] = {}
_REPO_ROOT_LOCK = threading.Lock()


def repository_root(start: Path) -> Path:
    key = str(start.resolve())
    with _REPO_ROOT_LOCK:
        cached = _REPO_ROOT_CACHE.get(key)
    if cached is not None:
        return cached
    value = str(git(start.resolve(), "rev-parse", "--show-toplevel")).strip()
    if not value:
        raise AG2CError(f"not a Git worktree: {start}")
    root = Path(value).resolve()
    with _REPO_ROOT_LOCK:
        _REPO_ROOT_CACHE[key] = root
        _REPO_ROOT_CACHE.setdefault(str(root), root)
    return root


def canonical_worktree(start: Path, *, root: Path | None = None) -> Path:
    resolved = root if root is not None else repository_root(start)
    listing = str(git(resolved, "worktree", "list", "--porcelain"))
    first = next((line[9:] for line in listing.splitlines() if line.startswith("worktree ")), "")
    if not first:
        raise AG2CError("Git did not report a canonical worktree")
    return Path(first).resolve()


def current_branch(root: Path) -> str:
    branch = str(git(root, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)).strip()
    if not branch:
        raise AG2CError("AG2C requires a named branch; detached HEAD is not supported")
    return branch


def head(root: Path) -> str:
    return str(git(root, "rev-parse", "HEAD")).strip()


def is_ancestor(root: Path, ancestor: str, commit: str) -> bool:
    try:
        git(root, "merge-base", "--is-ancestor", ancestor, commit)
        return True
    except AG2CError:
        return False


def rebase_worktree(root: Path, onto: str, *, stash_message: str) -> None:
    before = [line for line in str(git(root, "stash", "list")).splitlines() if line.strip()]
    git(root, "stash", "push", "--include-untracked", "--message", stash_message, check=False)
    after = [line for line in str(git(root, "stash", "list")).splitlines() if line.strip()]
    stashed = len(after) > len(before)
    try:
        git(root, "-c", "sequence.editor=true", "rebase", onto)
    except AG2CError as exc:
        git(root, "rebase", "--abort", check=False)
        if stashed:
            git(root, "stash", "pop", check=False)
        raise AG2CError(f"cannot rebase task worktree onto {onto}: {exc}") from exc
    if stashed:
        try:
            git(root, "stash", "pop")
        except AG2CError as exc:
            raise AG2CError(f"rebased onto {onto} but local changes could not be restored: {exc}") from exc


def status_entries(root: Path) -> list[str]:
    raw = git(root, "status", "--porcelain=v1", "-z", binary=True)
    assert isinstance(raw, bytes)
    entries = [entry for entry in raw.split(b"\0") if entry]
    paths: list[str] = []
    index = 0
    while index < len(entries):
        entry = entries[index]
        code = entry[:2].decode("ascii", errors="replace")
        paths.append(entry[3:].decode("utf-8", errors="replace").replace("\\", "/"))
        if code[0] in {"R", "C"} and index + 1 < len(entries):
            index += 1
        index += 1
    return sorted(set(paths))


def changed_paths(root: Path, base: str, *, exclude_prefixes: tuple[str, ...] = ()) -> list[str]:
    raw = git(root, "diff", "--name-only", "--no-renames", "-z", "--diff-filter=ACMRD", base, binary=True)
    assert isinstance(raw, bytes)
    paths = {
        item.decode("utf-8", errors="replace").replace("\\", "/")
        for item in raw.split(b"\0")
        if item
    }
    untracked = git(root, "ls-files", "--others", "--exclude-standard", "-z", binary=True)
    assert isinstance(untracked, bytes)
    paths.update(
        item.decode("utf-8", errors="replace").replace("\\", "/")
        for item in untracked.split(b"\0")
        if item
    )
    normalized_excludes = tuple(prefix.replace("\\", "/").rstrip("/") + "/" for prefix in exclude_prefixes)
    return sorted(path for path in paths if not path.startswith(normalized_excludes))


def _stage_modes(root: Path) -> dict[str, bytes]:
    raw = git(root, "ls-files", "--stage", "-z", binary=True)
    assert isinstance(raw, bytes)
    modes: dict[str, bytes] = {}
    for entry in raw.split(b"\0"):
        if not entry or b"\t" not in entry:
            continue
        metadata, _, relative = entry.partition(b"\t")
        mode = metadata.split(b" ", 1)[0]
        modes[relative.decode("utf-8", errors="replace").replace("\\", "/")] = mode
    return modes


def _hash_worktree_files(root: Path, relatives: list[str]) -> dict[str, str]:
    if not relatives:
        return {}
    wanted = set(relatives)
    with tempfile.TemporaryDirectory() as directory:
        extra = {"GIT_INDEX_FILE": str(Path(directory) / "index")}
        git(root, "read-tree", "HEAD", env=extra)
        git(root, "add", "-A", env=extra)
        raw = git(root, "ls-files", "--stage", "-z", binary=True, env=extra)
    assert isinstance(raw, bytes)
    object_ids: dict[str, str] = {}
    for entry in raw.split(b"\0"):
        if not entry or b"\t" not in entry:
            continue
        metadata, _, relative_bytes = entry.partition(b"\t")
        relative = relative_bytes.decode("utf-8", errors="replace").replace("\\", "/")
        if relative not in wanted:
            continue
        object_ids[relative] = metadata.split()[1].decode("ascii")
    missing = wanted - set(object_ids)
    if missing:
        raise AG2CError("unable to hash changed files: " + ", ".join(sorted(missing)[:8]))
    return object_ids


def _tree_entries(root: Path, commit: str) -> dict[str, tuple[bytes, bytes, bytes]]:
    raw = git(root, "ls-tree", "-r", "-z", commit, binary=True)
    assert isinstance(raw, bytes)
    entries: dict[str, tuple[bytes, bytes, bytes]] = {}
    for entry in raw.split(b"\0"):
        if not entry or b"\t" not in entry:
            continue
        metadata, _, relative = entry.partition(b"\t")
        mode, object_type, object_id = metadata.split(b" ", 2)
        entries[relative.decode("utf-8", errors="replace").replace("\\", "/")] = (mode, object_type, object_id)
    return entries


def change_digest(root: Path, base: str, *, exclude_prefixes: tuple[str, ...] = ()) -> str:
    digest = hashlib.sha256()
    digest.update(base.encode("ascii"))
    file_mode_enabled = str(git(root, "config", "--bool", "core.fileMode", check=False)).strip() == "true"
    relatives = changed_paths(root, base, exclude_prefixes=exclude_prefixes)
    stage_modes = {} if file_mode_enabled else _stage_modes(root)
    object_ids = _hash_worktree_files(
        root,
        [
            relative
            for relative in relatives
            if (root / relative).is_file() and not (root / relative).is_symlink()
        ],
    )
    for relative in relatives:
        path = root / relative
        digest.update(b"\0")
        digest.update(relative.encode("utf-8"))
        if path.is_symlink():
            digest.update(b"\0symlink\0")
            digest.update(path.readlink().as_posix().encode("utf-8"))
        elif path.is_file():
            staged_mode = stage_modes.get(relative)
            if file_mode_enabled or staged_mode is None:
                executable = bool(path.stat().st_mode & stat.S_IXUSR)
            else:
                executable = staged_mode == b"100755"
            digest.update(b"\0file+x\0" if executable else b"\0file\0")
            digest.update(object_ids[relative].encode("ascii"))
        elif path.exists():
            digest.update(b"\0other\0")
        else:
            digest.update(b"\0deleted\0")
    return digest.hexdigest()


def commit_changed_paths(
    root: Path,
    base: str,
    commit: str,
    *,
    exclude_prefixes: tuple[str, ...] = (),
) -> list[str]:
    raw = git(root, "diff", "--name-only", "--no-renames", "-z", "--diff-filter=ACMRD", base, commit, binary=True)
    assert isinstance(raw, bytes)
    excludes = tuple(prefix.replace("\\", "/").rstrip("/") + "/" for prefix in exclude_prefixes)
    return sorted(
        path
        for item in raw.split(b"\0")
        if item
        for path in [item.decode("utf-8", errors="replace").replace("\\", "/")]
        if not path.startswith(excludes)
    )


def commit_change_digest(
    root: Path,
    base: str,
    commit: str,
    *,
    exclude_prefixes: tuple[str, ...] = (),
) -> str:
    digest = hashlib.sha256()
    digest.update(base.encode("ascii"))
    tree_entries = _tree_entries(root, commit)
    for relative in commit_changed_paths(root, base, commit, exclude_prefixes=exclude_prefixes):
        digest.update(b"\0")
        digest.update(relative.encode("utf-8"))
        entry = tree_entries.get(relative)
        if not entry:
            digest.update(b"\0deleted\0")
            continue
        mode, object_type, object_id = entry
        if mode == b"120000":
            digest.update(b"\0symlink\0")
            content = git(root, "cat-file", "blob", object_id.decode("ascii"), binary=True)
            assert isinstance(content, bytes)
            digest.update(content)
        elif object_type == b"blob":
            digest.update(b"\0file+x\0" if mode == b"100755" else b"\0file\0")
            digest.update(object_id)
        else:
            digest.update(b"\0other\0")
    return digest.hexdigest()


def _parse_numstat(raw: bytes, excludes: tuple[str, ...]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in raw.split(b"\0"):
        if not item:
            continue
        added_b, removed_b, path_b = item.split(b"\t", 2)
        path = path_b.decode("utf-8", errors="replace").replace("\\", "/")
        if path.startswith(excludes):
            continue
        rows.append(
            {
                "path": path,
                "added": None if added_b == b"-" else int(added_b),
                "removed": None if removed_b == b"-" else int(removed_b),
            }
        )
    return rows


def _normalized_excludes(exclude_prefixes: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(prefix.replace("\\", "/").rstrip("/") + "/" for prefix in exclude_prefixes)


def _untracked_line_deltas(root: Path, excludes: tuple[str, ...]) -> list[dict[str, Any]]:
    """Untracked files never appear in `git diff`; count their lines as all-added.

    Binary detection mirrors git's own heuristic (NUL byte in the first 8000
    bytes) so the counts match numstat once the file is committed.
    """
    raw = git(root, "ls-files", "--others", "--exclude-standard", "-z", binary=True)
    assert isinstance(raw, bytes)
    rows: list[dict[str, Any]] = []
    for item in raw.split(b"\0"):
        if not item:
            continue
        path = item.decode("utf-8", errors="replace").replace("\\", "/")
        if path.startswith(excludes):
            continue
        target = root / path
        if not target.is_file() or target.is_symlink():
            continue
        content = target.read_bytes()
        if b"\0" in content[:8000]:
            rows.append({"path": path, "added": None, "removed": None})
            continue
        added = content.count(b"\n") + (1 if content and not content.endswith(b"\n") else 0)
        rows.append({"path": path, "added": added, "removed": 0})
    return rows


def line_deltas(root: Path, base: str, *, exclude_prefixes: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    """Per-file added/removed line counts between base and the WORKING TREE.

    Used at receipt time, when the verified change is still uncommitted.
    """
    excludes = _normalized_excludes(exclude_prefixes)
    raw = git(root, "diff", "--numstat", "--no-renames", "-z", "--diff-filter=ACMRD", base, binary=True)
    assert isinstance(raw, bytes)
    rows = _parse_numstat(raw, excludes) + _untracked_line_deltas(root, excludes)
    rows.sort(key=lambda row: row["path"])
    return rows


def commit_line_deltas(
    root: Path,
    base: str,
    commit: str,
    *,
    exclude_prefixes: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Per-file added/removed line counts between base and commit.

    Binary files record None counts (git numstat prints '-'). Paths follow
    commit_changed_paths conventions: --no-renames, -z termination, forward
    slashes, sorted, same exclude prefixes.
    """
    excludes = _normalized_excludes(exclude_prefixes)
    raw = git(root, "diff", "--numstat", "--no-renames", "-z", "--diff-filter=ACMRD", base, commit, binary=True)
    assert isinstance(raw, bytes)
    rows = _parse_numstat(raw, excludes)
    rows.sort(key=lambda row: row["path"])
    return rows

from .git_runtime import _runtime_data_root, _default_bundled_root, _git_exe_in, _shipped_git_roots, shipped_git_root, shipped_git_executable, _candidate_bundled_roots, _dirs_under, _git_layout_root, git_search_dirs, _env_path, git_command_env, peek_git_executable, _discover_git_dir, _common_git_dir, read_local_git_source, _sha256_file, _download_mingit_zip, _extract_mingit, _install_lock, install_git_runtime, ensure_bundled_git, _classify_executable, seize_existing_git, which_command, _persist_git_source
