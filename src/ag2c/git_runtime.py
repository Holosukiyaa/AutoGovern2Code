"""Extracted by flatten-split."""
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
from .gitops import GIT_SOURCE_BUNDLED, GIT_SOURCE_CONFIG_KEY, GIT_SOURCE_SYSTEM, MINGIT_SHA256, MINGIT_URL, MINGIT_ZIP_NAME, _BUNDLED_GIT_BIN_RELATIVE, _GIT_NAMES, _MISSING_GIT, _MISSING_GIT_UNIX, _run_git, bundled_git_root, git_executable, system_git_executable

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
