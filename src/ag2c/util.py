from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any

from .errors import ConfigurationError

PORTABLE_MARKER = "portable.ini"
_FALSE = {"0", "false", "no", "off"}
_TRUE = {"1", "true", "yes", "on"}


def hidden_process_kwargs() -> dict[str, Any]:
    """Hide the console window Windows creates for each git/checker child."""
    if os.name != "nt":
        return {}
    import subprocess

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return {
        "startupinfo": startupinfo,
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
    }


def portable_home() -> Path | None:
    configured = os.environ.get("AG2C_PORTABLE", "").strip()
    if configured.lower() in _FALSE:
        return None
    if configured and configured.lower() not in _TRUE:
        path = Path(configured).expanduser()
        try:
            path = path.resolve()
        except OSError:
            return None
        if path.is_dir():
            return path
        return path.parent if path.parent.is_dir() else None
    roots: list[Path] = []
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        roots.append(exe.parent)
        roots.append(exe.parent.parent)
    else:
        checkout = Path(__file__).resolve().parents[2]
        if (checkout / "src" / "ag2c" / "util.py").is_file():
            roots.append(checkout)
    for root in roots:
        if (root / PORTABLE_MARKER).is_file():
            return root
    if configured.lower() in _TRUE and roots:
        return roots[0]
    return None


def installed_data_root() -> Path:
    """Per-user store used by the installed app. Never follows portable.ini."""
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return (Path(local) / "AutoGovern2Code").resolve()
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return (Path(xdg) / "AutoGovern2Code").expanduser().resolve()
    return (Path.home() / ".local" / "share" / "AutoGovern2Code").resolve()


def default_data_root() -> Path:
    configured = os.environ.get("AG2C_DATA_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    home = portable_home()
    if home is not None:
        return (home / "data").resolve()
    return installed_data_root()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def digest_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize_artifact_path(value: str) -> str:
    normalized = value.replace("\\", "/").strip("/")
    parts = PurePosixPath(normalized).parts
    if not normalized or normalized == "." or any(part in {"", ".", ".."} for part in parts):
        raise ConfigurationError(f"artifact path must be a normalized relative path: {value!r}")
    return normalized


def path_matches(path: str, pattern: str) -> bool:
    path = path.replace("\\", "/").strip("/")
    pattern = pattern.replace("\\", "/").strip("/")
    if pattern in {"", "**"}:
        return True
    if pattern.endswith("/**"):
        prefix = pattern[:-3].rstrip("/")
        if path == prefix or path.startswith(prefix + "/"):
            return True
    expression = ""
    index = 0
    while index < len(pattern):
        if pattern[index:index + 3] == "**/":
            expression += "(?:.*/)?"
            index += 3
        elif pattern[index:index + 2] == "**":
            expression += ".*"
            index += 2
        elif pattern[index] == "*":
            expression += "[^/]*"
            index += 1
        elif pattern[index] == "?":
            expression += "[^/]"
            index += 1
        else:
            expression += re.escape(pattern[index])
            index += 1
    return re.fullmatch(expression, path) is not None


def relative_config_path(value: str, label: str) -> str:
    candidate = value.replace("\\", "/").strip()
    if not candidate or Path(candidate).is_absolute():
        raise ConfigurationError(f"{label} must be a non-empty relative path")
    return candidate
