from __future__ import annotations

import hashlib
import stat
import subprocess
from pathlib import Path

from .errors import AG2CError


def git(root: Path, *args: str, check: bool = True, binary: bool = False) -> str | bytes:
    resolved_root = root.expanduser().resolve()
    try:
        completed = subprocess.run(
            # The project path is explicitly selected by the local user. Pass a
            # per-invocation trust exception so Windows Git's ownership check
            # does not require changing the user's global configuration.
            ["git", "-c", f"safe.directory={resolved_root}", "-C", str(resolved_root), *args],
            check=False,
            capture_output=True,
            text=not binary,
            encoding=None if binary else "utf-8",
            errors=None if binary else "replace",
            shell=False,
        )
    except OSError as exc:
        raise AG2CError(f"cannot execute Git: {exc}") from exc
    if check and completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace") if binary else completed.stderr
        raise AG2CError(f"Git command failed ({' '.join(args)}): {str(stderr).strip()}")
    return completed.stdout


def repository_root(start: Path) -> Path:
    value = str(git(start.resolve(), "rev-parse", "--show-toplevel")).strip()
    if not value:
        raise AG2CError(f"not a Git worktree: {start}")
    return Path(value).resolve()


def canonical_worktree(start: Path) -> Path:
    root = repository_root(start)
    listing = str(git(root, "worktree", "list", "--porcelain"))
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


def change_digest(root: Path, base: str, *, exclude_prefixes: tuple[str, ...] = ()) -> str:
    digest = hashlib.sha256()
    digest.update(base.encode("ascii"))
    file_mode_enabled = str(git(root, "config", "--bool", "core.fileMode", check=False)).strip() == "true"
    for relative in changed_paths(root, base, exclude_prefixes=exclude_prefixes):
        path = root / relative
        digest.update(b"\0")
        digest.update(relative.encode("utf-8"))
        if path.is_symlink():
            digest.update(b"\0symlink\0")
            digest.update(path.readlink().as_posix().encode("utf-8"))
        elif path.is_file():
            staged = git(root, "ls-files", "--stage", "-z", "--", relative, binary=True)
            assert isinstance(staged, bytes)
            if file_mode_enabled or not staged:
                executable = bool(path.stat().st_mode & stat.S_IXUSR)
            else:
                executable = staged.startswith(b"100755 ")
            digest.update(b"\0file+x\0" if executable else b"\0file\0")
            object_id = str(git(root, "hash-object", f"--path={relative}", "--", relative)).strip()
            digest.update(object_id.encode("ascii"))
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
    for relative in commit_changed_paths(root, base, commit, exclude_prefixes=exclude_prefixes):
        digest.update(b"\0")
        digest.update(relative.encode("utf-8"))
        entry = git(root, "ls-tree", "-z", commit, "--", relative, binary=True)
        assert isinstance(entry, bytes)
        if not entry:
            digest.update(b"\0deleted\0")
            continue
        metadata, _, _ = entry.partition(b"\t")
        mode, object_type, object_id = metadata.split(b" ", 2)
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
