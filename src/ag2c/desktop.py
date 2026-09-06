from __future__ import annotations

import json
import threading
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import __version__
from .errors import AG2CError
from .management import (
    add_project,
    align_managed_projects,
    managed_projects,
    project_details,
    repair_and_check_project,
    stop_managing,
    uninstall_project,
)

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
        self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        self.send_header("X-AG2C-Desktop", f"desktop/{__version__}")
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

    def do_GET(self) -> None:
        if not self._host_allowed() or not self._origin_allowed():
            self._error(HTTPStatus.FORBIDDEN, "request origin is not allowed")
            return
        path = urlparse(self.path).path
        if path == "/api/status":
            self._json(
                HTTPStatus.OK,
                {
                    "status": "ready",
                    "version": __version__,
                    "capabilities": ["native-ui", "project-details", "knowledge-graph"],
                },
            )
            return
        if not self._authorized():
            if path.startswith("/api/"):
                self._error(HTTPStatus.UNAUTHORIZED, "desktop session token is required")
            else:
                self._error(HTTPStatus.NOT_FOUND, "not found")
            return
        if path == "/api/projects":
            self._json(
                HTTPStatus.OK,
                {
                    "projects": managed_projects(),
                    "version": __version__,
                },
            )
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
                self._json(
                    HTTPStatus.OK,
                    project_details(self._request_path(body), refresh=bool(body.get("refresh"))),
                )
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
    from .storage import ensure_portable_archive

    ensure_portable_archive()
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
