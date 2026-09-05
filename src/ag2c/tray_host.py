"""Tray host helpers with no GUI toolkit import."""

from __future__ import annotations

import json
import os
import secrets
import socket
import sys
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .util import hidden_process_kwargs

FILTERS = (
    ("", "全部"),
    ("exploring", "开工"),
    ("opaque", "黑盒"),
    ("unowned", "无主"),
    ("stale", "过期"),
    ("unreviewed", "未普查"),
    ("ambiguous", "重复认领"),
    ("abandoned", "废弃未清"),
    ("undeclared", "未验收"),
    ("writing", "AI正在写"),
)

STATE_LABELS = {
    "protected": "治理检查已通过",
    "attention": "需要处理",
    "missing": "目录不可用",
    "stopped": "治理已关闭",
    "inactive": "未生效",
}

FLAG_LABELS = {
    "exploring": "开工",
    "opaque": "黑盒",
    "unowned": "无主",
    "abandoned": "废弃未清",
    "stale": "过期",
    "unreviewed": "未普查",
    "ambiguous": "重复认领",
    "undeclared": "未验收",
    "writing": "AI正在写",
}

MUTEX_NAME = r"Local\AutoGovern2Code.Desktop"
STARTUP_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_VALUE = "AutoGovern2Code"
APP_KEY = r"Software\AutoGovern2Code"
APP_PATHS_KEY = r"Software\Microsoft\Windows\CurrentVersion\App Paths\AutoGovern2Code.exe"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\AutoGovern2Code"


def app_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def is_portable(args: list[str] | None, app_dir: Path | None = None) -> bool:
    if args:
        for arg in args:
            if arg.lower() == "--portable":
                return True
    root = app_dir or app_directory()
    return (root / "portable.ini").is_file()


def _windowless_python() -> str:
    executable = sys.executable
    if os.name != "nt" or getattr(sys, "frozen", False):
        return executable
    path = Path(executable)
    if path.name.lower() == "python.exe":
        pythonw = path.with_name("pythonw.exe")
        if pythonw.is_file():
            return str(pythonw)
    return executable


def runtime_command(args: list[str] | None, app_dir: Path | None = None) -> list[str]:
    if args:
        for arg in args:
            if arg.startswith("--runtime="):
                return [str(Path(arg.split("=", 1)[1]).resolve())]
    root = app_dir or app_directory()
    frozen = root / "ag2c" / "ag2c.exe"
    if frozen.is_file():
        return [str(frozen)]
    return [_windowless_python(), "-m", "ag2c"]


def session_token() -> str:
    return secrets.token_urlsafe(32)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def portable_env(app_dir: Path) -> dict[str, str]:
    home = str(app_dir)
    return {
        "AG2C_PORTABLE": home,
        "AG2C_DATA_ROOT": str(app_dir / "data"),
        "AG2C_PORTABLE_GIT": str(app_dir / "git"),
    }


def text(row: dict[str, Any] | None, key: str) -> str:
    if not row or key not in row or row[key] is None:
        return ""
    return str(row[key])


def string_list(row: dict[str, Any] | None, key: str) -> list[str]:
    values = row.get(key) if row else None
    if not isinstance(values, list):
        return []
    return [str(item) for item in values if str(item)]


def flag_label(flag: str) -> str:
    return FLAG_LABELS.get(flag, flag)


def first_flag_label(node: dict[str, Any]) -> str:
    flags = node.get("flags")
    if isinstance(flags, list) and flags:
        return flag_label(str(flags[0]))
    label = text(node, "statusLabel")
    return label or text(node, "role")


def state_label(state: str) -> str:
    return STATE_LABELS.get(state, "未生效")


def has_flag(node: dict[str, Any], flag: str) -> bool:
    flags = node.get("flags")
    if isinstance(flags, list) and flag in {str(item) for item in flags}:
        return True
    if flag == "abandoned" and text(node, "role") == "leftover":
        return True
    return text(node, "role") == flag


def node_matches(node: dict[str, Any], query: str, flag: str) -> bool:
    if flag and not has_flag(node, flag):
        return False
    needle = (query or "").strip().lower()
    if not needle:
        return True
    blob = " ".join(
        [
            text(node, "title"),
            text(node, "path"),
            text(node, "summary"),
            text(node, "id"),
        ]
    ).lower()
    return needle in blob


def file_relpath(node: dict[str, Any]) -> str:
    path = text(node, "path").replace("\\", "/")
    if ":" in path:
        path = path.split(":", 1)[1]
    return path.strip("/")


def inspect_fields(node: dict[str, Any]) -> dict[str, str]:
    who = text(node, "coverageLabel") or "、".join(string_list(node, "coveredBy"))
    floors = "、".join(string_list(node, "floors")) or text(node, "floorLabel")
    when = text(node, "lastCommit") or text(node, "changedAt")
    role = text(node, "roleLabel") or first_flag_label(node)
    title = text(node, "title") or text(node, "path") or "点文件树或知识卡"
    return {
        "title": title,
        "status": first_flag_label(node),
        "summary": text(node, "summary"),
        "who": who or "—",
        "floors": floors or "—",
        "when": when or "—",
        "role": role or "—",
        "path": text(node, "path") or "—",
    }


def coverage_rows(details: dict[str, Any] | None, query: str, flag: str) -> tuple[list[tuple[str, dict[str, Any]]], list[dict[str, Any]], str]:
    files: list[tuple[str, dict[str, Any]]] = []
    cards: list[dict[str, Any]] = []
    headline = "点文件树或知识卡查看归属。"
    if not details:
        return files, cards, "选择一个项目后，这里显示谁管理文件、是不是开工或黑盒。"
    graph = details.get("graph") if isinstance(details.get("graph"), dict) else {}
    raw_headline = graph.get("headline")
    if raw_headline:
        headline = str(raw_headline)
    nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    for raw in nodes:
        if not isinstance(raw, dict):
            continue
        kind = text(raw, "kind")
        if kind in {"knowledge", "gap", "work"}:
            if node_matches(raw, query, flag):
                cards.append(raw)
            continue
        if kind != "file" or not node_matches(raw, query, flag):
            continue
        rel = file_relpath(raw)
        if rel:
            files.append((rel, raw))
    return files, cards, headline


class DesktopApi:
    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.token = token

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"X-AG2C-Token": self.token}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.base_url + path.lstrip("/"),
            data=payload,
            method=method,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(_error_message(detail, str(exc))) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(str(exc.reason or exc)) from exc
        if not raw.strip():
            return {}
        data = json.loads(raw)
        if not isinstance(data, dict):
            return {}
        return data


def _error_message(text_body: str, fallback: str) -> str:
    try:
        payload = json.loads(text_body)
    except json.JSONDecodeError:
        return fallback
    if isinstance(payload, dict) and payload.get("error"):
        return str(payload["error"])
    return fallback


def wait_for_status(
    api: DesktopApi,
    attempts: int = 100,
    pause: float = 0.1,
    cancelled: Callable[[], bool] | None = None,
) -> bool:
    import time

    for _ in range(attempts):
        if cancelled is not None and cancelled():
            return False
        try:
            api.request("GET", "api/status")
            return True
        except Exception:
            time.sleep(pause)
    return False


def acquire_mutex() -> Any | None:
    if os.name != "nt":
        return object()
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    handle = kernel32.CreateMutexW(None, True, MUTEX_NAME)
    if ctypes.get_last_error() == 183:
        return None
    return handle


def startup_enabled() -> bool:
    if os.name != "nt":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_KEY) as key:
            winreg.QueryValueEx(key, STARTUP_VALUE)
            return True
    except OSError:
        return False


def apply_startup(enabled: bool, executable: str) -> None:
    if os.name != "nt":
        return
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, STARTUP_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, STARTUP_VALUE, 0, winreg.REG_SZ, f'"{executable}"')
        else:
            try:
                winreg.DeleteValue(key, STARTUP_VALUE)
            except OSError:
                pass


def register_app(executable: str, version: str = "0.8.4") -> None:
    if os.name != "nt":
        return
    import winreg

    exe = str(Path(executable).resolve())
    home = str(Path(exe).parent)
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, APP_KEY) as key:
            winreg.SetValueEx(key, "InstallPath", 0, winreg.REG_SZ, home)
            winreg.SetValueEx(key, "Version", 0, winreg.REG_SZ, version)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, APP_PATHS_KEY) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, exe)
            winreg.SetValueEx(key, "Path", 0, winreg.REG_SZ, home)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "AutoGovern2Code")
            winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, version)
            winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, "AutoGovern2Code contributors")
            winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, home)
            winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, f'"{exe}" --unregister')
            winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)
    except OSError:
        pass


def unregister_app() -> None:
    if os.name != "nt":
        return
    import winreg

    for key in (APP_PATHS_KEY, UNINSTALL_KEY, APP_KEY):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
        except OSError:
            pass
    apply_startup(False, "")


def start_desktop_server(command: list[str], port: int, token: str, extra_env: dict[str, str] | None = None):
    import subprocess

    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    args = list(command) + ["desktop", "serve", "--port", str(port), "--token", token]
    kwargs: dict[str, Any] = {
        "args": args,
        "env": env,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        **hidden_process_kwargs(),
    }
    if os.name == "nt" and len(command) == 1 and command[0].lower().endswith("ag2c.exe"):
        kwargs["cwd"] = str(Path(command[0]).parent)
    return subprocess.Popen(**kwargs)


def stop_desktop_server(api: DesktopApi | None, process) -> None:
    def _shutdown() -> None:
        if api is None:
            return
        try:
            api.request("POST", "api/shutdown", {})
        except Exception:
            pass

    worker = threading.Thread(target=_shutdown, daemon=True)
    worker.start()
    worker.join(1.0)
    if process is not None and process.poll() is None:
        try:
            process.terminate()
            process.wait(timeout=1.5)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
