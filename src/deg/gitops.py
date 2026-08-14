from __future__ import annotations

import hashlib
import stat
import subprocess
from pathlib import Path

from .errors import DEGError


def git(root: Path, *args: str, check: bool = True, binary: bool = False) -> str | bytes:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            capture_output=True,
            text=not binary,
            encoding=None if binary else "utf-8",
            errors=None if binary else "replace",
            shell=False,
        )
    except OSError as exc:
        raise DEGError(f"cannot execute Git: {exc}") from exc
    if check and completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace") if binary else completed.stderr
        raise DEGError(f"Git command failed ({' '.join(args)}): {str(stderr).strip()}")
    return completed.stdout


def repository_root(start: Path) -> Path:
    value = str(git(start.resolve(), "rev-parse", "--show-toplevel")).strip()
    if not value:
        raise DEGError(f"not a Git worktree: {start}")
    return Path(value).resolve()


def canonical_worktree(start: Path) -> Path:
    root = repository_root(start)
    listing = str(git(root, "worktree", "list", "--porcelain"))
    first = next((line[9:] for line in listing.splitlines() if line.startswith("worktree ")), "")
    if not first:
        raise DEGError("Git did not report a canonical worktree")
    return Path(first).resolve()


def current_branch(root: Path) -> str:
    branch = str(git(root, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)).strip()
    if not branch:
        raise DEGError("DEG requires a named branch; detached HEAD is not supported")
    return branch


def head(root: Path) -> str:
    return str(git(root, "rev-parse", "HEAD")).strip()


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


def changed_paths(root: Path, base: str) -> list[str]:
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
    return sorted(paths)


def change_digest(root: Path, base: str) -> str:
    digest = hashlib.sha256()
    digest.update(base.encode("ascii"))
    for relative in changed_paths(root, base):
        path = root / relative
        digest.update(b"\0")
        digest.update(relative.encode("utf-8"))
        if path.is_symlink():
            digest.update(b"\0symlink\0")
            digest.update(path.readlink().as_posix().encode("utf-8"))
        elif path.is_file():
            executable = bool(path.stat().st_mode & stat.S_IXUSR)
            digest.update(b"\0file+x\0" if executable else b"\0file\0")
            digest.update(path.read_bytes())
        elif path.exists():
            digest.update(b"\0other\0")
        else:
            digest.update(b"\0deleted\0")
    return digest.hexdigest()
