from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from contextlib import contextmanager
from pathlib import Path

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


def _runtime_data_root() -> Path:
    from .util import default_data_root

    return default_data_root()


def _default_bundled_root() -> Path:
    return _runtime_data_root() / "runtime" / "git"


def _git_exe_in(root: Path | None) -> str | None:
    if root is None or not root.is_dir():
        return None
    for relative in _BUNDLED_GIT_BIN_RELATIVE:
        directory = root.joinpath(*relative.split("/"))
        for name in _GIT_NAMES:
            candidate = directory / name
            if candidate.is_file():
                return str(candidate.resolve())
    return None


def _shipped_git_roots() -> list[Path]:
    roots: list[Path] = []
    override = os.environ.get("AG2C_PORTABLE_GIT", "").strip()
    if override:
        roots.append(Path(override).expanduser().resolve())
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        roots.append(exe_dir / "git")
        roots.append(exe_dir.parent / "git")
    unique: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if root in seen:
            continue
        seen.add(root)
        unique.append(root)
    return unique


def shipped_git_root() -> Path | None:
    for root in _shipped_git_roots():
        if _git_exe_in(root):
            return root
    return None


def shipped_git_executable() -> str | None:
    return _git_exe_in(shipped_git_root())


def _candidate_bundled_roots() -> list[Path]:
    roots: list[Path] = []
    override = os.environ.get("AG2C_GIT_ROOT", "").strip()
    if override:
        roots.append(Path(override).expanduser().resolve())
    roots.extend(_shipped_git_roots())
    roots.append(_default_bundled_root())
    unique: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if root in seen:
            continue
        seen.add(root)
        unique.append(root)
    return unique


def bundled_git_root() -> Path | None:
    for root in _candidate_bundled_roots():
        if _git_exe_in(root):
            return root
    return None


def _dirs_under(root: Path) -> list[Path]:
    dirs: list[Path] = []
    for relative in _BUNDLED_GIT_BIN_RELATIVE:
        candidate = root.joinpath(*relative.split("/"))
        if candidate.is_dir():
            dirs.append(candidate)
    return dirs


def _git_layout_root(executable: str) -> Path | None:
    exe = Path(executable).resolve()
    parent = exe.parent
    grand = parent.parent
    for candidate in (grand, parent):
        if _dirs_under(candidate):
            return candidate
    return parent if parent.is_dir() else None


def git_search_dirs(executable: str | None = None) -> list[Path]:
    if executable:
        layout = _git_layout_root(executable)
        if layout is not None:
            return _dirs_under(layout) or [Path(executable).resolve().parent]
    root = bundled_git_root()
    if root is None:
        return []
    return _dirs_under(root)


def _env_path(env: dict[str, str]) -> tuple[str, str]:
    for key, value in env.items():
        if key.upper() == "PATH":
            return key, value
    return "PATH", ""


def git_command_env(base: dict[str, str] | None = None, *, executable: str | None = None) -> dict[str, str]:
    run_env = os.environ.copy() if base is None else dict(base)
    extra = [str(path) for path in git_search_dirs(executable)]
    if extra:
        path_key, current = _env_path(run_env)
        run_env[path_key] = os.pathsep.join([*extra, current])
    return run_env


def system_git_executable() -> str | None:
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


def peek_git_executable() -> str | None:
    override = os.environ.get("AG2C_GIT", "").strip()
    if override:
        path = Path(override).expanduser()
        return str(path.resolve()) if path.is_file() else None
    return shipped_git_executable() or _git_exe_in(bundled_git_root()) or system_git_executable()


def _discover_git_dir(root: Path) -> Path | None:
    marker = root / ".git"
    if marker.is_dir():
        return marker.resolve()
    if not marker.is_file():
        return None
    try:
        text = marker.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        if line.lower().startswith("gitdir:"):
            path = Path(line.split(":", 1)[1].strip())
            resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
            return resolved if resolved.exists() else None
    return None


def _common_git_dir(root: Path) -> Path | None:
    git_dir = _discover_git_dir(root)
    if git_dir is None:
        return None
    commondir = git_dir / "commondir"
    if not commondir.is_file():
        return git_dir
    try:
        rel = commondir.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return git_dir
    path = Path(rel)
    resolved = path.resolve() if path.is_absolute() else (git_dir / path).resolve()
    return resolved if resolved.exists() else git_dir


def read_local_git_source(root: Path) -> str:
    git_dir = _common_git_dir(root)
    if git_dir is None:
        return ""
    config = git_dir / "config"
    if not config.is_file():
        return ""
    try:
        text = config.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    section = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip().strip('"').lower()
            continue
        if section != "ag2c" or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip().lower() == "git-source":
            source = value.strip().strip('"')
            if source in {GIT_SOURCE_SYSTEM, GIT_SOURCE_BUNDLED}:
                return source
    return ""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _download_mingit_zip(destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    print(f"AG2C: downloading bundled Git ({MINGIT_ZIP_NAME})...", file=sys.stderr, flush=True)
    staging = destination.with_suffix(destination.suffix + ".part")
    try:
        with urllib.request.urlopen(MINGIT_URL, timeout=300) as response, staging.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 64)
                if not chunk:
                    break
                handle.write(chunk)
        if _sha256_file(staging) != MINGIT_SHA256:
            raise AG2CError("downloaded bundled Git failed SHA-256 verification", code=GIT_MISSING)
        staging.replace(destination)
    except AG2CError:
        staging.unlink(missing_ok=True)
        raise
    except (OSError, urllib.error.URLError) as exc:
        staging.unlink(missing_ok=True)
        raise AG2CError(f"could not download bundled Git: {exc}", code=GIT_MISSING) from exc


def _extract_mingit(zip_path: Path, destination: Path) -> None:
    staging = destination.with_name(destination.name + ".staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(staging)
        if _git_exe_in(staging) is None:
            raise AG2CError("bundled Git archive did not contain git.exe", code=GIT_MISSING)
        if destination.exists():
            shutil.rmtree(destination)
        staging.replace(destination)
    except AG2CError:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise
    except (OSError, zipfile.BadZipFile) as exc:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise AG2CError(f"could not unpack bundled Git: {exc}", code=GIT_MISSING) from exc


@contextmanager
def _install_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = None
    for _ in range(120):
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            break
        except FileExistsError:
            time.sleep(0.5)
    if fd is None:
        raise AG2CError("timed out waiting for bundled Git download", code=GIT_MISSING)
    try:
        yield
    finally:
        os.close(fd)
        path.unlink(missing_ok=True)


def install_git_runtime(destination: Path) -> str:
    destination = destination.expanduser().resolve()
    existing = _git_exe_in(destination)
    if existing:
        return existing
    if os.name != "nt":
        raise AG2CError(_MISSING_GIT_UNIX, code=GIT_MISSING)
    if os.environ.get("AG2C_SKIP_GIT_DOWNLOAD") == "1":
        raise AG2CError(_MISSING_GIT, code=GIT_MISSING)
    cache = destination.parent / "cache"
    lock = cache / f"{MINGIT_ZIP_NAME}.lock"
    with _install_lock(lock):
        existing = _git_exe_in(destination)
        if existing:
            return existing
        zip_override = os.environ.get("AG2C_MINGIT_ZIP", "").strip()
        zip_path = Path(zip_override).expanduser().resolve() if zip_override else cache / MINGIT_ZIP_NAME
        if zip_override:
            if not zip_path.is_file():
                raise AG2CError(f"bundled Git archive is missing: {zip_path}", code=GIT_MISSING)
            if _sha256_file(zip_path) != MINGIT_SHA256:
                raise AG2CError("bundled Git archive failed SHA-256 verification", code=GIT_MISSING)
        elif not zip_path.is_file() or _sha256_file(zip_path) != MINGIT_SHA256:
            _download_mingit_zip(zip_path)
        _extract_mingit(zip_path, destination)
    installed = _git_exe_in(destination)
    if not installed:
        raise AG2CError(_MISSING_GIT, code=GIT_MISSING)
    return installed


def ensure_bundled_git() -> str:
    existing = _git_exe_in(bundled_git_root())
    if existing:
        return existing
    if os.environ.get("AG2C_GIT_ROOT", "").strip():
        raise AG2CError(_MISSING_GIT, code=GIT_MISSING)
    if os.name != "nt":
        raise AG2CError(_MISSING_GIT_UNIX, code=GIT_MISSING)
    if os.environ.get("AG2C_SKIP_GIT_DOWNLOAD") == "1":
        raise AG2CError(_MISSING_GIT, code=GIT_MISSING)
    return install_git_runtime(_default_bundled_root())


def _classify_executable(executable: str) -> str:
    try:
        resolved = Path(executable).resolve()
    except OSError:
        return GIT_SOURCE_SYSTEM
    for candidate in (shipped_git_executable(), _git_exe_in(bundled_git_root())):
        try:
            if candidate and resolved == Path(candidate).resolve():
                return GIT_SOURCE_BUNDLED
        except OSError:
            continue
    return GIT_SOURCE_SYSTEM


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


def seize_existing_git(root: Path) -> str:
    """Keep the project's `.git` and history. Force AG2C operations onto bundled MinGit."""
    existing = shipped_git_executable() or _git_exe_in(bundled_git_root())
    if existing:
        _persist_git_source(root, existing)
        return existing
    try:
        executable = ensure_bundled_git()
    except AG2CError:
        executable = git_executable(root)
    _persist_git_source(root, executable)
    return executable


def which_command(name: str) -> str | None:
    if Path(name).name.lower() in {"git", "git.exe"}:
        try:
            return git_executable()
        except AG2CError as exc:
            if exc.code == GIT_MISSING:
                return None
            raise
    extra = git_search_dirs()
    if extra:
        _, search = _env_path(git_command_env())
        found = shutil.which(name, path=search or None)
    else:
        found = shutil.which(name)
    if found:
        return found
    if Path(name).stem.lower() in {"python", "python3"}:
        return sys.executable
    return None


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


def _persist_git_source(root: Path, executable: str) -> None:
    if os.environ.get("AG2C_GIT", "").strip():
        return
    if _common_git_dir(root) is None:
        return
    source = _classify_executable(executable)
    current = read_local_git_source(root)
    if current == GIT_SOURCE_BUNDLED:
        return
    if current == source:
        return
    writer = system_git_executable() or executable
    try:
        _run_git(writer, root, "config", "--local", GIT_SOURCE_CONFIG_KEY, source, check=False)
    except AG2CError:
        pass


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
    _persist_git_source(resolved_root, executable)
    return output


def repository_root(start: Path) -> Path:
    value = str(git(start.resolve(), "rev-parse", "--show-toplevel")).strip()
    if not value:
        raise AG2CError(f"not a Git worktree: {start}")
    return Path(value).resolve()


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
