"""WebView2 shell host. This is the product window."""

from __future__ import annotations

import json
import sys
import time
from typing import Any

from .tray_host import (
    DesktopApi,
    acquire_mutex,
    app_directory,
    free_port,
    portable_env,
    runtime_command,
    session_token,
    start_desktop_server,
    stop_desktop_server,
    wait_for_status,
)
from .webview_ui import UI_APP_JS, UI_INDEX_HTML, UI_LAYOUT_CSS

WEBVIEW2_RUNTIME_URL = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
MISSING_PYWEBVIEW = (
    "pywebview is required for the AutoGovern2Code WebView2 window. "
    "pip install 'autogovern2code[gui]'\n"
)
MISSING_RUNTIME = (
    "WebView2 Runtime is not installed. Install it from "
    f"{WEBVIEW2_RUNTIME_URL} then retry.\n"
)
UI_CSP = (
    "default-src 'self'; script-src 'self'; connect-src 'self'; "
    "style-src 'self'; frame-ancestors 'none'"
)
_UI_PAGES = {
    "/ui": ("text/html; charset=utf-8", UI_INDEX_HTML),
    "/ui/": ("text/html; charset=utf-8", UI_INDEX_HTML),
    "/ui/index.html": ("text/html; charset=utf-8", UI_INDEX_HTML),
    "/ui/layout.css": ("text/css; charset=utf-8", UI_LAYOUT_CSS),
    "/ui/app.js": ("text/javascript; charset=utf-8", UI_APP_JS),
}


def ui_page(path: str) -> tuple[str, bytes] | None:
    item = _UI_PAGES.get(path)
    if item is None:
        return None
    content_type, text = item
    return content_type, text.encode("utf-8")


def web_ui_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/ui/"


def inject_token_js(token: str) -> str:
    return (
        "window.__AG2C_TOKEN = "
        + json.dumps(token)
        + "; if (typeof window.ag2cFetchStatus === 'function') { window.ag2cFetchStatus(); }"
        + " if (typeof window.ag2cFetchDashboard === 'function') { window.ag2cFetchDashboard(); }"
    )


def _import_webview() -> Any | None:
    try:
        import webview
    except ImportError:
        return None
    return webview


def _runtime_missing(exc: BaseException) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return any(needle in text for needle in ("webview2", "edgechromium"))


def _wait_page_status(window: Any, token: str, attempts: int = 50) -> dict[str, Any] | None:
    script = inject_token_js(token)
    for _ in range(attempts):
        window.evaluate_js(script)
        raw = window.evaluate_js("window.__AG2C_STATUS_JSON || ''")
        if raw:
            if isinstance(raw, dict) and raw.get("status") == "ready":
                return raw
            try:
                payload = json.loads(raw) if isinstance(raw, str) else None
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict) and payload.get("status") == "ready":
                return payload
        time.sleep(0.1)
    return None


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    probe = any(item.lower() == "--probe" for item in args)
    portable = any(item.lower() == "--portable" for item in args)
    webview = _import_webview()
    if webview is None:
        sys.stderr.write(MISSING_PYWEBVIEW)
        return 2
    mutex = acquire_mutex()
    if mutex is None:
        if probe:
            sys.stderr.write("AutoGovern2Code desktop is already running.\n")
            return 1
        return 0
    token = session_token()
    port = free_port()
    extra = portable_env(app_directory()) if portable else None
    runtime_args = [item for item in args if item.lower().startswith("--runtime=")]
    process = start_desktop_server(runtime_command(runtime_args), port, token, extra)
    api = DesktopApi(f"http://127.0.0.1:{port}/", token)
    try:
        if not wait_for_status(api):
            sys.stderr.write("AG2C 本地服务启动超时。\n")
            return 1
        result: dict[str, Any] = {"payload": None}
        window = webview.create_window(
            "AutoGovern2Code",
            url=web_ui_url(port),
            hidden=probe,
            text_select=True,
        )

        def on_loaded() -> None:
            if probe:
                result["payload"] = _wait_page_status(window, token)
                window.destroy()
                return
            window.evaluate_js(inject_token_js(token))

        window.events.loaded += on_loaded
        start_kwargs: dict[str, Any] = {}
        if sys.platform == "win32":
            start_kwargs["gui"] = "edgechromium"
        try:
            webview.start(**start_kwargs)
        except Exception as exc:
            if _runtime_missing(exc):
                sys.stderr.write(MISSING_RUNTIME)
                return 2
            raise
        if probe:
            payload = result.get("payload")
            if not isinstance(payload, dict) or payload.get("status") != "ready":
                sys.stderr.write("WebView2 page did not reach /api/status.\n")
                return 1
            native = getattr(window, "native", None)
            print(f"OK: webview probed /api/status ready hwnd={native!r}")
        return 0
    finally:
        stop_desktop_server(api, process)


if __name__ == "__main__":
    raise SystemExit(main())
