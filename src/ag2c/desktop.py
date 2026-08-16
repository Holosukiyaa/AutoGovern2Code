from __future__ import annotations

import json
import mimetypes
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlparse

from . import __version__
from .errors import AG2CError
from .management import add_project, managed_projects, repair_and_check_project, stop_managing
from .tasks import evidence

MAX_BODY = 64 * 1024


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

    def _authorized(self) -> bool:
        return self.headers.get("X-AG2C-Token", "") == self.server.token

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
        self.end_headers()

    def _json(self, status: int, value: object) -> None:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(payload))
        self.wfile.write(payload)

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"error": message})

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
        if path == "/assets/styles.css":
            self._static("styles.css", "text/css")
            return
        if path == "/assets/app.js":
            self._static("app.js", "application/javascript")
            return
        if path == "/api/status":
            self._json(HTTPStatus.OK, {"status": "ready", "version": __version__})
            return
        if not self._authorized():
            self._error(HTTPStatus.UNAUTHORIZED, "desktop session token is required")
            return
        if path == "/api/projects":
            self._json(HTTPStatus.OK, {"projects": managed_projects()})
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
            if path == "/api/projects/add":
                self._json(HTTPStatus.OK, {"project": add_project(self._request_path(body))})
                return
            if path == "/api/projects/check":
                self._json(HTTPStatus.OK, {"project": repair_and_check_project(self._request_path(body))})
                return
            if path == "/api/projects/remove":
                self._json(HTTPStatus.OK, stop_managing(self._request_path(body)))
                return
            if path == "/api/evidence":
                self._json(HTTPStatus.OK, evidence(self._request_path(body)))
                return
            if path == "/api/shutdown":
                self._json(HTTPStatus.OK, {"status": "stopping"})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
        except (AG2CError, OSError, ValueError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        self._error(HTTPStatus.NOT_FOUND, "not found")


def serve_desktop(*, port: int, token: str) -> int:
    if not 1 <= port <= 65535:
        raise AG2CError("desktop port must be between 1 and 65535")
    if len(token) < 24:
        raise AG2CError("desktop session token is too short")
    server = DesktopServer(("127.0.0.1", port), token)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
