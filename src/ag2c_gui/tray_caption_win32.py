"""Win32 caption layer for the tray: ctypes API loading, HWND discovery, dark caption, maximize/drag.

Kept separate from imgui_tray so the main program only deals with ImGui panels;
everything here is native window chrome and only does work on Windows.
"""

from __future__ import annotations

import os
from pathlib import Path

_CAPTION_HWND = 0
_CAPTION_API = None
_GLFW_DLL = None


def _caption_api():
    """Win32 handles must be pointer-sized; ctypes defaults truncate HWND on x64."""
    global _CAPTION_API
    if _CAPTION_API is not None:
        return _CAPTION_API
    import ctypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    user32.FindWindowW.restype = ctypes.c_void_p
    user32.GetActiveWindow.restype = ctypes.c_void_p
    user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
    user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
    user32.IsWindowVisible.restype = ctypes.c_int
    user32.IsWindow.argtypes = [ctypes.c_void_p]
    user32.IsWindow.restype = ctypes.c_int
    user32.SetWindowPos.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    user32.SetWindowPos.restype = ctypes.c_int
    user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user32.ShowWindow.restype = ctypes.c_int
    user32.IsZoomed.argtypes = [ctypes.c_void_p]
    user32.IsZoomed.restype = ctypes.c_int
    user32.ReleaseCapture.restype = ctypes.c_int
    user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_size_t]
    user32.SendMessageW.restype = ctypes.c_ssize_t
    dwmapi.DwmSetWindowAttribute.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
    dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long
    kernel32.GetCurrentProcessId.restype = ctypes.c_ulong
    _CAPTION_API = (ctypes, user32, dwmapi, kernel32)
    return _CAPTION_API


def _glfw_dll(ctypes_mod):
    global _GLFW_DLL
    if _GLFW_DLL is not None:
        return _GLFW_DLL
    import imgui_bundle

    dll = ctypes_mod.WinDLL(str(Path(imgui_bundle.__file__).resolve().parent / "glfw3.dll"))
    dll.glfwGetWin32Window.argtypes = [ctypes_mod.c_void_p]
    dll.glfwGetWin32Window.restype = ctypes_mod.c_void_p
    dll.glfwMaximizeWindow.argtypes = [ctypes_mod.c_void_p]
    dll.glfwRestoreWindow.argtypes = [ctypes_mod.c_void_p]
    dll.glfwGetWindowAttrib.argtypes = [ctypes_mod.c_void_p, ctypes_mod.c_int]
    dll.glfwGetWindowAttrib.restype = ctypes_mod.c_int
    _GLFW_DLL = dll
    return dll


def _glfw_hwnd(ctypes_mod) -> int:
    """HWND of the running Hello ImGui GLFW window, if the backend is up."""
    try:
        from imgui_bundle import hello_imgui

        addr = int(hello_imgui.get_glfw_window_address() or 0)
        if not addr:
            return 0
        return int(_glfw_dll(ctypes_mod).glfwGetWin32Window(addr) or 0)
    except Exception:
        return 0


def _enum_tray_hwnd(ctypes_mod, user32, kernel32) -> int:
    pid = int(kernel32.GetCurrentProcessId())
    found = ctypes_mod.c_void_p(0)
    enum_proc = ctypes_mod.WINFUNCTYPE(ctypes_mod.c_int, ctypes_mod.c_void_p, ctypes_mod.c_void_p)

    def callback(hwnd, _lparam):
        proc = ctypes_mod.c_ulong(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes_mod.byref(proc))
        if int(proc.value) != pid or not user32.IsWindowVisible(hwnd):
            return 1
        buf = ctypes_mod.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        if buf.value == "AutoGovern2Code":
            found.value = hwnd
            return 0
        return 1

    user32.EnumWindows.argtypes = [enum_proc, ctypes_mod.c_void_p]
    user32.EnumWindows.restype = ctypes_mod.c_int
    user32.EnumWindows(enum_proc(callback), None)
    return int(found.value or 0)


def _tray_hwnd(ctypes_mod, user32, kernel32) -> int:
    global _CAPTION_HWND
    if _CAPTION_HWND and user32.IsWindow(_CAPTION_HWND):
        return int(_CAPTION_HWND)
    hwnd = _glfw_hwnd(ctypes_mod)
    if hwnd:
        return hwnd
    active = int(user32.GetActiveWindow() or 0)
    if active:
        buf = ctypes_mod.create_unicode_buffer(512)
        user32.GetWindowTextW(active, buf, 512)
        if buf.value == "AutoGovern2Code":
            return active
    hwnd = int(user32.FindWindowW("GLFW30", "AutoGovern2Code") or 0)
    if hwnd:
        return hwnd
    hwnd = int(user32.FindWindowW(None, "AutoGovern2Code") or 0)
    if hwnd:
        return hwnd
    return _enum_tray_hwnd(ctypes_mod, user32, kernel32)


def _apply_dark_caption() -> None:
    """Paint the native caption the same dark as the tray, not the Windows accent green."""
    if os.name != "nt":
        return
    try:
        ctypes_mod, user32, dwmapi, kernel32 = _caption_api()
        hwnd = _tray_hwnd(ctypes_mod, user32, kernel32)
        if not hwnd:
            return
        global _CAPTION_HWND
        if hwnd == _CAPTION_HWND:
            return
        dark = ctypes_mod.c_int(1)
        none_backdrop = ctypes_mod.c_int(1)
        for attr in (20, 19):
            dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes_mod.byref(dark), ctypes_mod.sizeof(dark))
        dwmapi.DwmSetWindowAttribute(hwnd, 38, ctypes_mod.byref(none_backdrop), ctypes_mod.sizeof(none_backdrop))
        # COLORREF 0x00BBGGRR. 0x00000000 is treated as "use accent" on some Win11 builds.
        caption = ctypes_mod.c_uint(0x00292421)
        text_color = ctypes_mod.c_uint(0x00E6E4E1)
        dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes_mod.byref(caption), ctypes_mod.sizeof(caption))
        dwmapi.DwmSetWindowAttribute(hwnd, 34, ctypes_mod.byref(caption), ctypes_mod.sizeof(caption))
        dwmapi.DwmSetWindowAttribute(hwnd, 36, ctypes_mod.byref(text_color), ctypes_mod.sizeof(text_color))
        if hwnd != _CAPTION_HWND:
            user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0037)
            _CAPTION_HWND = hwnd
    except OSError:
        return


def _window_chrome():
    if os.name != "nt":
        return 0, None
    try:
        ctypes_mod, user32, _dwmapi, kernel32 = _caption_api()
        return _tray_hwnd(ctypes_mod, user32, kernel32), user32
    except OSError:
        return 0, None


def _window_is_maximized(hwnd: int, user32) -> bool:
    if hwnd and user32 is not None and user32.IsZoomed(hwnd):
        return True
    try:
        from imgui_bundle import hello_imgui

        ctypes_mod, _u, _d, _k = _caption_api()
        addr = int(hello_imgui.get_glfw_window_address() or 0)
        if addr:
            return bool(_glfw_dll(ctypes_mod).glfwGetWindowAttrib(addr, 0x00020008))
    except Exception:
        pass
    return False


def _caption_press(*, double: bool) -> None:
    proof = os.environ.get("AG2C_CAPTION_PROOF") or str(Path(os.environ.get("TEMP", ".")) / "ag2c-caption-proof.txt")
    try:
        Path(proof).write_text("double" if double else "drag", encoding="utf-8")
    except OSError:
        pass
    hwnd, user32 = _window_chrome()
    if not hwnd or user32 is None:
        return
    if double:
        try:
            from imgui_bundle import hello_imgui

            ctypes_mod, _user32, _dwmapi, _kernel32 = _caption_api()
            addr = int(hello_imgui.get_glfw_window_address() or 0)
            dll = _glfw_dll(ctypes_mod)
            maximized = bool(addr and dll.glfwGetWindowAttrib(addr, 0x00020008)) or bool(user32.IsZoomed(hwnd))
            if addr:
                if maximized:
                    dll.glfwRestoreWindow(addr)
                else:
                    dll.glfwMaximizeWindow(addr)
            else:
                user32.ShowWindow(hwnd, 9 if maximized else 3)
        except Exception:
            user32.ShowWindow(hwnd, 9 if user32.IsZoomed(hwnd) else 3)
        return
    user32.ReleaseCapture()
    user32.SendMessageW(hwnd, 0x00A1, 2, 0)
