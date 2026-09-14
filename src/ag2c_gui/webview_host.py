"""WebView2 shell host. Coexists with the Hello ImGui tray until W5."""

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
UI_INDEX_HTML = """<!DOCTYPE html>
<html lang="zh-Hans">
<head>
<meta charset="utf-8">
<title>AutoGovern2Code</title>
<link rel="stylesheet" href="/ui/layout.css">
</head>
<body>
<p id="status"></p>
<p id="attention"></p>
<section id="action"><h2>要你处理</h2><ul></ul></section>
<section id="alert"><h2>系统警情</h2><ul></ul></section>
<section id="record"><h2>记录</h2><ul></ul></section>
<script src="/ui/app.js"></script>
</body>
</html>
"""
UI_LAYOUT_CSS = """:root {
  --danger: #f24c40;
  --decision: #f2b340;
  --notice: #b38738;
  --ok: #66946b;
  --muted: #7a7a80;
  --bg: #1c1c1f;
  --fg: #ececec;
}
html, body { margin: 0; background: var(--bg); color: var(--fg); font: 15px/1.45 sans-serif; }
#attention { font-size: 1.35rem; padding: 0.75rem 1rem; }
section { padding: 0.5rem 1rem 1rem; }
h2 { color: var(--muted); font-size: 0.95rem; margin: 0 0 0.4rem; }
ul { margin: 0; padding-left: 1.2rem; }
li.error { color: var(--danger); }
li.warn { color: var(--decision); }
li.ok { color: var(--ok); }
"""
UI_APP_JS = """function headers() {
  var h = {};
  if (window.__AG2C_TOKEN) {
    h["X-AG2C-Token"] = window.__AG2C_TOKEN;
  }
  return h;
}
function fillList(id, rows) {
  var ul = document.querySelector("#" + id + " ul");
  if (!ul) return;
  ul.innerHTML = "";
  (rows || []).forEach(function (row) {
    var li = document.createElement("li");
    li.className = row.severity || "";
    li.textContent = row.text || "";
    ul.appendChild(li);
  });
}
function recordRows(records) {
  var rows = [];
  var health = (records && records.health) || [];
  health.forEach(function (item) {
    rows.push({ severity: "ok", text: (item.label || "") + "：" + String(item.value) });
  });
  ["patrol", "hazards", "token"].forEach(function (key) {
    ((records && records[key]) || []).forEach(function (row) { rows.push(row); });
  });
  return rows;
}
window.ag2cFetchStatus = function () {
  var node = document.getElementById("status");
  fetch("/api/status", { headers: headers(), credentials: "omit" })
    .then(function (res) {
      if (!res.ok) throw new Error(String(res.status));
      return res.json();
    })
    .then(function (body) {
      window.__AG2C_STATUS = body;
      window.__AG2C_STATUS_JSON = JSON.stringify(body);
      if (node) node.textContent = body.status || "";
    })
    .catch(function (err) {
      window.__AG2C_STATUS_ERROR = String(err);
      if (node) node.textContent = "error";
    });
};
window.ag2cFetchDashboard = function () {
  var attention = document.getElementById("attention");
  fetch("/api/projects", { headers: headers(), credentials: "omit" })
    .then(function (res) { return res.ok ? res.json() : { projects: [] }; })
    .then(function (listing) {
      var projects = listing.projects || [];
      var body = {};
      if (projects.length && projects[0].root) {
        body.path = projects[0].root;
      }
      return fetch("/api/project/dashboard", {
        method: "POST",
        headers: Object.assign({ "Content-Type": "application/json" }, headers()),
        credentials: "omit",
        body: JSON.stringify(body)
      });
    })
    .then(function (res) {
      if (!res.ok) throw new Error(String(res.status));
      return res.json();
    })
    .then(function (model) {
      window.__AG2C_DASHBOARD = model;
      if (attention) attention.textContent = (model.attention && model.attention.text) || "";
      fillList("action", model.actions);
      fillList("alert", model.alerts);
      fillList("record", recordRows(model.records));
    })
    .catch(function (err) {
      window.__AG2C_DASHBOARD_ERROR = String(err);
      if (attention) attention.textContent = "error";
    });
};
if (window.__AG2C_TOKEN) {
  window.ag2cFetchStatus();
  window.ag2cFetchDashboard();
}
"""
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
