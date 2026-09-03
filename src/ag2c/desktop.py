from __future__ import annotations

import json
import mimetypes
import os
import string
import subprocess
import sys
import threading
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlparse

from . import __version__
from .errors import AG2CError
from .management import (
    add_project,
    align_managed_projects,
    managed_projects,
    project_details,
    projects_revision,
    repair_and_check_project,
    stop_managing,
    uninstall_project,
)
from .tasks import evidence

MAX_BODY = 64 * 1024
FOLDER_PICKER_TITLE = "选择要纳入 AutoGovern2Code 治理的 Git 项目"


class _PickerCancelled(Exception):
    pass


class _PickerUnavailable(Exception):
    pass


def list_project_folders(path: Path | None = None) -> dict[str, object]:
    if path is None:
        roots = (
            [Path(f"{letter}:\\") for letter in string.ascii_uppercase if Path(f"{letter}:\\").is_dir()]
            if os.name == "nt"
            else [Path("/")]
        )
        return {
            "path": None,
            "parent": None,
            "is_git": False,
            "directories": [
                {"name": str(root), "path": str(root), "is_git": (root / ".git").exists()}
                for root in roots
            ],
            "truncated": False,
        }
    resolved = path.expanduser().resolve()
    if not resolved.is_dir():
        raise AG2CError(f"folder is unavailable: {resolved}")
    try:
        children = [child for child in resolved.iterdir() if child.is_dir()]
    except OSError as exc:
        raise AG2CError(f"cannot read folder {resolved}: {exc}") from exc
    children.sort(key=lambda item: item.name.lower())
    truncated = len(children) > 1000
    children = children[:1000]
    parent = None if resolved.parent == resolved else str(resolved.parent)
    return {
        "path": str(resolved),
        "parent": parent,
        "is_git": (resolved / ".git").exists(),
        "directories": [
            {"name": child.name, "path": str(child), "is_git": (child / ".git").exists()}
            for child in children
        ],
        "truncated": truncated,
    }


def describe_picked_folder(path: Path | None) -> dict[str, object]:
    if path is None:
        return {"cancelled": True, "unavailable": False, "path": None, "is_git": False}
    resolved = path.expanduser().resolve()
    if not resolved.is_dir():
        raise AG2CError(f"folder is unavailable: {resolved}")
    return {
        "cancelled": False,
        "unavailable": False,
        "path": str(resolved),
        "is_git": (resolved / ".git").exists(),
    }


def pick_project_folder() -> dict[str, object]:
    selected: list[str | None] = []
    errors: list[BaseException] = []

    def run() -> None:
        try:
            selected.append(_native_folder_path())
        except BaseException as exc:
            errors.append(exc)

    if os.name == "nt":
        thread = threading.Thread(target=_run_windows_sta, args=(run,), name="ag2c-folder-picker", daemon=True)
        thread.start()
        thread.join()
    else:
        run()
    if any(isinstance(exc, _PickerCancelled) for exc in errors) or (selected and selected[0] is None):
        return describe_picked_folder(None)
    if errors or not selected:
        return {"cancelled": False, "unavailable": True, "path": None, "is_git": False}
    return describe_picked_folder(Path(selected[0]))


def _run_windows_sta(callback: Callable[[], None]) -> None:
    import ctypes
    from ctypes.wintypes import DWORD

    ole32 = ctypes.windll.ole32
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, DWORD]
    ole32.CoInitializeEx.restype = ctypes.HRESULT
    status = ole32.CoInitializeEx(None, 2)
    try:
        callback()
    finally:
        if status in (0, 1):
            ole32.CoUninitialize()


def _native_folder_path() -> str | None:
    pickers = (
        (_pick_folder_windows_dialog, _pick_folder_tkinter)
        if os.name == "nt"
        else (_pick_folder_macos_dialog, _pick_folder_linux_dialog, _pick_folder_tkinter)
        if sys.platform == "darwin"
        else (_pick_folder_linux_dialog, _pick_folder_tkinter)
    )
    for picker in pickers:
        try:
            return picker()
        except _PickerCancelled:
            return None
        except _PickerUnavailable:
            continue
    raise AG2CError("native folder picker is unavailable")


def _vtable(pointer: object):
    import ctypes

    return ctypes.cast(ctypes.cast(pointer, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))


def _windows_guid(value: str):
    import ctypes
    from ctypes import byref, c_wchar_p

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", ctypes.c_ulong),
            ("Data2", ctypes.c_ushort),
            ("Data3", ctypes.c_ushort),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    guid = GUID()
    status = ctypes.windll.ole32.CLSIDFromString(c_wchar_p(value), byref(guid))
    if status:
        raise _PickerUnavailable(f"invalid COM id: {value}")
    return guid


def _windows_owner_hwnd() -> int:
    import ctypes
    from ctypes.wintypes import HWND, LPCWSTR

    user32 = ctypes.windll.user32
    user32.FindWindowW.argtypes = [LPCWSTR, LPCWSTR]
    user32.FindWindowW.restype = HWND
    user32.GetForegroundWindow.restype = HWND
    hwnd = user32.FindWindowW(None, "AutoGovern2Code")
    if hwnd:
        return int(hwnd)
    foreground = user32.GetForegroundWindow()
    return int(foreground) if foreground else 0


def _force_foreground(hwnd: int) -> None:
    import ctypes
    from ctypes.wintypes import BOOL, DWORD, HWND

    if not hwnd:
        return
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.AllowSetForegroundWindow(0xFFFFFFFF)
    user32.GetForegroundWindow.restype = HWND
    user32.GetWindowThreadProcessId.restype = DWORD
    user32.AttachThreadInput.argtypes = [DWORD, DWORD, BOOL]
    user32.AttachThreadInput.restype = BOOL
    kernel32.GetCurrentThreadId.restype = DWORD
    current = kernel32.GetCurrentThreadId()
    foreground = user32.GetForegroundWindow()
    target_tid = user32.GetWindowThreadProcessId(hwnd, None)
    attached: list[int] = []
    for other in {user32.GetWindowThreadProcessId(foreground, None) if foreground else 0, target_tid}:
        if other and other != current:
            if user32.AttachThreadInput(current, other, True):
                attached.append(other)
    try:
        user32.ShowWindow(hwnd, 9)
        user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 3)
        user32.SetForegroundWindow(hwnd)
        user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 3)
    finally:
        for other in attached:
            user32.AttachThreadInput(current, other, False)


def _focus_window_with_title(title: str, stop: threading.Event) -> None:
    import ctypes
    import time
    from ctypes.wintypes import BOOL, HWND, LPARAM

    user32 = ctypes.windll.user32
    callback_type = ctypes.WINFUNCTYPE(BOOL, HWND, LPARAM)
    raised = {"done": False}

    def each(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        text = buffer.value or ""
        if text != title and title not in text and "选择文件夹" not in text:
            return True
        _force_foreground(int(hwnd))
        raised["done"] = True
        return False

    enumerate_windows = callback_type(each)
    for _ in range(40):
        if stop.is_set() or raised["done"]:
            return
        user32.EnumWindows(enumerate_windows, 0)
        time.sleep(0.05)


def _windows_dialog_cancelled(status: int) -> bool:
    code = status & 0xFFFFFFFF
    return code in {0x80004004, 0x800704C7, 0x800704C8} or code in {1223, 0x4C7}


def _windows_show_result(status: int) -> None:
    if status:
        raise _PickerCancelled()


def _release_com(pointer: object) -> None:
    import ctypes
    from ctypes import c_void_p
    from ctypes.wintypes import DWORD

    if not getattr(pointer, "value", None):
        return
    try:
        ctypes.WINFUNCTYPE(DWORD, c_void_p)(_vtable(pointer)[2])(pointer)
    except OSError:
        return


def _pick_folder_windows_dialog() -> str:
    if os.name != "nt":
        raise _PickerUnavailable("Windows folder dialog is not available")
    import ctypes
    from ctypes import HRESULT, POINTER, byref, c_void_p
    from ctypes.wintypes import DWORD, HWND, LPCWSTR, LPWSTR

    ole32 = ctypes.windll.ole32
    clsid = _windows_guid("{DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7}")
    iid = _windows_guid("{42F85136-DB7E-439C-85F1-E4075D135FC8}")
    dialog = c_void_p()
    created = ole32.CoCreateInstance(byref(clsid), None, 1, byref(iid), byref(dialog))
    if created or not dialog.value:
        raise _PickerUnavailable("Windows folder dialog could not be created")
    item = c_void_p()
    path_memory = LPWSTR()
    stop = threading.Event()
    try:
        table = _vtable(dialog)
        options = DWORD(0)
        get_options = ctypes.WINFUNCTYPE(HRESULT, c_void_p, POINTER(DWORD))(table[10])
        set_options = ctypes.WINFUNCTYPE(HRESULT, c_void_p, DWORD)(table[9])
        set_title = ctypes.WINFUNCTYPE(HRESULT, c_void_p, LPCWSTR)(table[17])
        show = ctypes.WINFUNCTYPE(HRESULT, c_void_p, HWND)(table[3])
        get_result = ctypes.WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_void_p))(table[20])
        if get_options(dialog, byref(options)):
            raise _PickerUnavailable("Windows folder dialog options are unavailable")
        if set_options(dialog, options.value | 0x20 | 0x40 | 0x800):
            raise _PickerUnavailable("Windows folder dialog could not pick folders")
        set_title(dialog, FOLDER_PICKER_TITLE)
        owner = _windows_owner_hwnd()
        if owner:
            _force_foreground(owner)
        focus = threading.Thread(
            target=_focus_window_with_title,
            args=(FOLDER_PICKER_TITLE, stop),
            name="ag2c-folder-focus",
            daemon=True,
        )
        focus.start()
        shown = show(dialog, owner or None)
        stop.set()
        _windows_show_result(int(shown))
        if get_result(dialog, byref(item)) or not item.value:
            raise _PickerCancelled()
        item_table = _vtable(item)
        get_name = ctypes.WINFUNCTYPE(HRESULT, c_void_p, DWORD, POINTER(LPWSTR))(item_table[5])
        if get_name(item, 0x80058000, byref(path_memory)) or not path_memory.value:
            raise _PickerCancelled()
        return path_memory.value
    finally:
        stop.set()
        if path_memory:
            try:
                ole32.CoTaskMemFree(path_memory)
            except OSError:
                pass
        _release_com(item)
        _release_com(dialog)


def _pick_folder_macos_dialog() -> str:
    if sys.platform != "darwin":
        raise _PickerUnavailable("macOS folder dialog is not available")
    escaped = FOLDER_PICKER_TITLE.replace("\\", "\\\\").replace('"', '\\"')
    completed = subprocess.run(
        ["osascript", "-e", f'POSIX path of (choose folder with prompt "{escaped}")'],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        message = (completed.stderr or "").strip().lower()
        if "user canceled" in message or "user cancelled" in message or not message:
            raise _PickerCancelled()
        raise _PickerUnavailable(completed.stderr.strip())
    selected = completed.stdout.strip().rstrip("/")
    if not selected:
        raise _PickerCancelled()
    return selected


def _pick_folder_linux_dialog() -> str:
    if sys.platform == "darwin" or os.name == "nt":
        raise _PickerUnavailable("Linux folder dialog is not available")
    commands = (
        ["zenity", "--file-selection", "--directory", f"--title={FOLDER_PICKER_TITLE}"],
        ["kdialog", "--getexistingdirectory", ".", FOLDER_PICKER_TITLE],
    )
    saw_dialog = False
    for command in commands:
        try:
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
        except FileNotFoundError:
            continue
        saw_dialog = True
        if completed.returncode != 0:
            raise _PickerCancelled()
        selected = completed.stdout.strip()
        if not selected:
            raise _PickerCancelled()
        return selected
    if not saw_dialog:
        raise _PickerUnavailable("no desktop folder dialog is installed")
    raise _PickerCancelled()


def _pick_folder_tkinter() -> str:
    try:
        import tkinter
        from tkinter import filedialog
    except ImportError as exc:
        raise _PickerUnavailable("tkinter folder dialog is not available") from exc
    root = tkinter.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except tkinter.TclError:
        pass
    try:
        selected = filedialog.askdirectory(parent=root, title=FOLDER_PICKER_TITLE, mustexist=True)
    finally:
        root.destroy()
    if not selected:
        raise _PickerCancelled()
    return selected


class DesktopServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], token: str):
        super().__init__(address, DesktopHandler)
        self.token = token


class DesktopHandler(BaseHTTPRequestHandler):
    server: DesktopServer

    def log_message(self, format: str, *args: object) -> None:
        return

    def _host_allowed(self) -> bool:
        host = self.headers.get("Host", "").split(":", 1)[0].strip("[]").lower()
        return host in {"127.0.0.1", "localhost"}

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        parsed = urlparse(origin)
        return parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}

    def _cookie_token(self) -> str:
        for part in self.headers.get("Cookie", "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == "ag2c-token":
                return value
        return ""

    def _authorized(self) -> bool:
        provided = self.headers.get("X-AG2C-Token", "") or self._cookie_token()
        return provided == self.server.token

    def _headers(self, status: int, content_type: str, length: int) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
        self.send_header("X-AG2C-Desktop", f"desktop/{__version__}")
        self.send_header("Set-Cookie", f"ag2c-token={self.server.token}; Path=/; SameSite=Strict; HttpOnly")
        self.end_headers()

    def _json(self, status: int, value: object) -> None:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(payload))
        self.wfile.write(payload)

    def _error(self, status: int, message: str, *, code: str | None = None) -> None:
        payload: dict[str, object] = {"error": message}
        if code:
            payload["code"] = code
        self._json(status, payload)

    def _read_json(self) -> dict[str, object]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise AG2CError("invalid request length") from exc
        if length < 0 or length > MAX_BODY:
            raise AG2CError("request body is too large")
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AG2CError("request body must be a JSON object") from exc
        if not isinstance(value, dict):
            raise AG2CError("request body must be a JSON object")
        return value

    def _request_path(self, body: dict[str, object]) -> Path:
        value = body.get("path")
        if not isinstance(value, str) or not value.strip():
            raise AG2CError("project path is required")
        return Path(value).expanduser().resolve()

    def _static(self, relative: str, content_type: str | None = None) -> None:
        if relative not in {"index.html", "styles.css", "app.js"}:
            self._error(HTTPStatus.NOT_FOUND, "not found")
            return
        resource = files("ag2c").joinpath("ui", relative)
        try:
            payload = resource.read_bytes()
        except (FileNotFoundError, OSError):
            self._error(HTTPStatus.NOT_FOUND, "desktop asset is missing")
            return
        media = content_type or mimetypes.guess_type(relative)[0] or "application/octet-stream"
        if media.startswith("text/") or media in {"application/javascript"}:
            media += "; charset=utf-8"
        self._headers(HTTPStatus.OK, media, len(payload))
        self.wfile.write(payload)

    def do_GET(self) -> None:
        if not self._host_allowed() or not self._origin_allowed():
            self._error(HTTPStatus.FORBIDDEN, "request origin is not allowed")
            return
        path = urlparse(self.path).path
        if path == "/":
            self._static("index.html", "text/html")
            return
        if path == "/assets/styles.css" or path.startswith("/assets/styles.css"):
            self._static("styles.css", "text/css")
            return
        if path == "/assets/app.js" or path.startswith("/assets/app.js"):
            self._static("app.js", "application/javascript")
            return
        if path == "/api/status":
            self._json(
                HTTPStatus.OK,
                {
                    "status": "ready",
                    "version": __version__,
                    "capabilities": ["web-folder-picker", "native-folder-picker", "project-details"],
                },
            )
            return
        if path == "/api/session":
            # Loopback viewers can recover after a restart or a missing bootstrap
            # query. Host and Origin checks already keep this off the network.
            self._json(HTTPStatus.OK, {"token": self.server.token})
            return
        if not self._authorized():
            self._error(HTTPStatus.UNAUTHORIZED, "desktop session token is required")
            return
        if path == "/api/projects":
            self._json(
                HTTPStatus.OK,
                {
                    "projects": managed_projects(),
                    "migrations": [],
                    "version": __version__,
                },
            )
            return
        if path == "/api/projects/revision":
            self._json(HTTPStatus.OK, projects_revision())
            return
        self._error(HTTPStatus.NOT_FOUND, "not found")

    def do_POST(self) -> None:
        if not self._host_allowed() or not self._origin_allowed():
            self._error(HTTPStatus.FORBIDDEN, "request origin is not allowed")
            return
        if not self._authorized():
            self._error(HTTPStatus.UNAUTHORIZED, "desktop session token is required")
            return
        path = urlparse(self.path).path
        try:
            body = self._read_json()
            if path == "/api/filesystem/list":
                requested = body.get("path")
                if requested is not None and (not isinstance(requested, str) or not requested.strip()):
                    raise AG2CError("folder path must be a non-empty string")
                self._json(
                    HTTPStatus.OK,
                    list_project_folders(Path(requested) if isinstance(requested, str) else None),
                )
                return
            if path == "/api/filesystem/pick":
                self._json(HTTPStatus.OK, pick_project_folder())
                return
            if path == "/api/projects/align":
                migrations = align_managed_projects()
                self._json(
                    HTTPStatus.OK,
                    {
                        "migrations": migrations,
                        "projects": managed_projects(),
                        "version": __version__,
                    },
                )
                return
            if path == "/api/projects/add":
                self._json(HTTPStatus.OK, {"project": add_project(self._request_path(body))})
                return
            if path == "/api/projects/check":
                self._json(HTTPStatus.OK, {"project": repair_and_check_project(self._request_path(body))})
                return
            if path == "/api/project/details":
                self._json(HTTPStatus.OK, project_details(self._request_path(body)))
                return
            if path == "/api/projects/remove":
                self._json(HTTPStatus.OK, stop_managing(self._request_path(body)))
                return
            if path == "/api/projects/uninstall":
                self._json(HTTPStatus.OK, uninstall_project(self._request_path(body)))
                return
            if path == "/api/projects/resume":
                self._json(HTTPStatus.OK, {"project": repair_and_check_project(self._request_path(body))})
                return
            if path == "/api/evidence":
                self._json(HTTPStatus.OK, evidence(self._request_path(body), verify_local=False))
                return
            if path == "/api/shutdown":
                self._json(HTTPStatus.OK, {"status": "stopping"})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
        except (AG2CError, OSError, ValueError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc), code=getattr(exc, "code", None))
            return
        self._error(HTTPStatus.NOT_FOUND, "not found")


def serve_desktop(*, port: int, token: str, on_ready: Callable[[int], object] | None = None) -> int:
    if not 1 <= port <= 65535:
        raise AG2CError("desktop port must be between 1 and 65535")
    if len(token) < 24:
        raise AG2CError("desktop session token is too short")
    server = DesktopServer(("127.0.0.1", port), token)
    try:
        if on_ready is not None:
            on_ready(server.server_address[1])
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
