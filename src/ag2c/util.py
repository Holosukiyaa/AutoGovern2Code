from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
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


def atomic_json_write(path: Path, value: dict[str, Any]) -> None:
    """原子写 JSON（临时文件 + os.replace）：治理状态文件的唯一写法。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def parse_iso8601(value: Any) -> datetime | None:
    """解析 ISO 时间串：非串/空白/非法 → None；裸时间按 UTC。

    合并自 audit._parse 与 token._parse_time 的双份拷贝（危房名单拆迁，
    2026-09-10）。取 token 版超集行为：解析前 strip——带首尾空白的输入
    从"返回 None"变为"解析成功"（更宽容，audit 侧无反向依赖）。
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def read_json(path: Path, *, what: str) -> dict[str, Any]:
    """读 JSON 治理文件：错误带用途标签，非对象拒绝。

    合并自 govern.py 与 enrollment.py 的双份 _read_json（危房名单首批拆迁，
    2026-09-09）：调用方用 what 保留各自的错误文案。"""
    from .errors import AG2CError

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AG2CError(f"cannot read {what} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AG2CError(f"{what} must contain an object: {path}")
    return value


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
