from __future__ import annotations

import json
import os
import threading
import uuid
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ag2c import __version__
from ag2c.errors import AG2CError
from ag2c.management import (
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

    def _headers(self, status: int, content_type: str, length: int, *, csp: str | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", csp or "default-src 'none'; frame-ancestors 'none'")
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
        from .webview_host import UI_CSP, ui_page

        page = ui_page(path)
        if page is not None:
            content_type, body = page
            self._headers(HTTPStatus.OK, content_type, len(body), csp=UI_CSP)
            self.wfile.write(body)
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
        if path == "/api/household/rehome-status":
            job_id = parse_qs(urlparse(self.path).query).get("id", [""])[0]
            job = _rehome_job(job_id)
            if job is None:
                self._error(HTTPStatus.NOT_FOUND, "unknown rehome job")
                return
            self._json(HTTPStatus.OK, job)
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
            if path == "/api/project/dashboard":
                from .dashboard import dashboard_model
                from .tray_host import selected_root_after_list

                requested = str(body.get("path") or "").strip()
                if not requested:
                    requested = selected_root_after_list(managed_projects(), "")
                if not requested:
                    self._json(HTTPStatus.OK, dashboard_model(None, None))
                    return
                details = project_details(Path(requested).expanduser().resolve(), refresh=bool(body.get("refresh")))
                guard = details.get("guard") if isinstance(details.get("guard"), dict) else {}
                self._json(HTTPStatus.OK, dashboard_model(details, guard))
                return
            if path == "/api/project/tree":
                from .tray_inspect import coverage_rows, empty_inspect

                details = None
                if str(body.get("path") or "").strip():
                    details = project_details(self._request_path(body), refresh=bool(body.get("refresh")))
                files, _cards, headline = coverage_rows(details, "", "")
                self._json(
                    HTTPStatus.OK,
                    {
                        "files": [{"path": rel, "title": (node.get("title") or rel)} for rel, node in files[:800]],
                        "headline": headline,
                        "inspect": empty_inspect(headline),
                    },
                )
                return
            if path == "/api/project/inspect":
                from .tray_host import append_audit
                from .tray_inspect import coverage_rows, empty_inspect, inspect_file

                details = None
                if str(body.get("path") or "").strip():
                    details = project_details(self._request_path(body), refresh=bool(body.get("refresh")))
                files, cards, headline = coverage_rows(details, "", "")
                wanted = str(body.get("file") or "").replace("\\", "/")
                payload = empty_inspect(headline)
                if wanted:
                    for rel, node in files:
                        if rel.replace("\\", "/") == wanted:
                            payload = inspect_file(node, files, cards)
                            append_audit([], "点击文件", "文件树", wanted)
                            break
                self._json(HTTPStatus.OK, payload)
                return
            if path == "/api/project/ops":
                from .tray_host import mcp_entry_text, mcp_health_snapshot, text

                tab = str(body.get("tab") or "audit")
                payload: dict = {"tab": tab}
                if tab == "audit":
                    log = Path(os.environ.get("AG2C_AUDIT_LOG") or Path(os.environ.get("TEMP", ".") or ".") / "ag2c-audit.log")
                    lines: list[str] = []
                    if log.is_file():
                        lines = [item.rstrip("\n") for item in log.read_text(encoding="utf-8", errors="replace").splitlines()[-200:]]
                    payload["lines"] = lines
                    self._json(HTTPStatus.OK, payload)
                    return
                details = None
                project: dict = {}
                if str(body.get("path") or "").strip():
                    root = self._request_path(body)
                    details = project_details(root, refresh=bool(body.get("refresh")))
                    project = next((row for row in managed_projects() if text(row, "root") == str(root)), {}) or {}
                if tab == "gate":
                    health = mcp_health_snapshot(
                        handshake=bool(body.get("handshake")),
                        cwd=text(project, "root") or None,
                        managed=bool(project.get("delivery_enforced")) if "delivery_enforced" in project else None,
                    )
                    payload["prompt"] = mcp_entry_text()
                    payload["mcp_health"] = health
                    payload["status"] = str(health.get("label") or "")
                elif tab == "records":
                    journal: list = []
                    try:
                        from ag2c.journal import list_journals

                        if project:
                            journal = [item for item in reversed(list_journals(Path(text(project, "root")))) if isinstance(item, dict)]
                    except Exception:
                        journal = []
                    payload["journal"] = journal
                    payload["completed_tasks"] = int(project.get("completed_tasks") or 0)
                    payload["product"] = project.get("product")
                elif tab == "worktrees":
                    worktrees = [item for item in ((details or {}).get("worktrees") or []) if isinstance(item, dict)]
                    payload["worktrees"] = worktrees
                    payload["open_tasks"] = int(project.get("open_tasks") or 0)
                else:
                    raise AG2CError("tab must be audit, gate, records, or worktrees")
                self._json(HTTPStatus.OK, payload)
                return
            if path == "/api/project/digest":
                from .tray_host import digest_triggers_reload

                payload = dict(_project_digest(self._request_path(body)))
                previous = str(body.get("previous") or "")
                current = str(payload.get("digest") or "")
                payload["reload"] = digest_triggers_reload(previous, current)
                self._json(HTTPStatus.OK, payload)
                return
            if path == "/api/project/audit-ack":
                from ag2c.audit import acknowledge
                from ag2c.config import discover_manifest, load_manifest

                root = self._request_path(body)
                manifest = load_manifest(discover_manifest(root), project_root=root)
                self._json(HTTPStatus.OK, {"acknowledged": acknowledge(manifest, actor="tray")})
                return
            if path == "/api/project/proxy":
                from ag2c.govern import configure_proxy

                flag = body.get("flag")
                if flag not in {"auto_settle", "auto_census", "auto_warning"}:
                    raise AG2CError("flag must be auto_settle, auto_census, or auto_warning")
                on = bool(body.get("on"))
                reason = body.get("reason")
                self._json(
                    HTTPStatus.OK,
                    configure_proxy(
                        self._request_path(body),
                        actor="tray",
                        reason=str(reason).strip() if isinstance(reason, str) and reason.strip() else "mayor 授 from 托管",
                        auto_settle=on if flag == "auto_settle" else None,
                        auto_census=on if flag == "auto_census" else None,
                        auto_warning=on if flag == "auto_warning" else None,
                    ),
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
            if path == "/api/household/rehome":
                card_id = body.get("id")
                target_room = body.get("targetRoom")
                if not isinstance(card_id, str) or not card_id.strip():
                    raise AG2CError("card id is required")
                if not isinstance(target_room, str) or not target_room.strip():
                    raise AG2CError("target room is required")
                target_subdir = body.get("targetSubdir")
                reason = body.get("reason")
                self._json(
                    HTTPStatus.OK,
                    _start_rehome_job(
                        self._request_path(body),
                        card_id=card_id.strip(),
                        target_room=target_room.strip(),
                        target_subdir=str(target_subdir).strip() if isinstance(target_subdir, str) else "",
                        reason=str(reason).strip() if isinstance(reason, str) and reason.strip() else "operator rehomed a file card from the tray",
                    ),
                )
                return
            if path == "/api/household/span":
                from ag2c.household_commands import set_household_span

                card_id = body.get("id")
                tag = body.get("tag")
                if not isinstance(card_id, str) or not card_id.strip():
                    raise AG2CError("household id is required")
                if not isinstance(tag, str) or not tag.strip():
                    raise AG2CError("coverage tag is required")
                reason = body.get("reason")
                self._json(
                    HTTPStatus.OK,
                    {
                        "project": set_household_span(
                            self._request_path(body),
                            card_id=card_id,
                            span=tag,
                            actor="tray",
                            reason=str(reason).strip() if isinstance(reason, str) and reason.strip() else "operator retagged coverage",
                        )
                    },
                )
                return
            if path == "/api/shutdown":
                self._json(HTTPStatus.OK, {"status": "stopping"})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
        except (AG2CError, OSError, ValueError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc), code=getattr(exc, "code", None))
            return
        self._error(HTTPStatus.NOT_FOUND, "not found")


_GUARD_CACHE: dict[str, tuple[float, dict[str, object]]] = {}
_GUARD_TTL_S = 10.0

_REHOME_JOBS: dict[str, dict[str, object]] = {}
_REHOME_LOCK = threading.Lock()


def _rehome_job(job_id: str) -> dict[str, object] | None:
    with _REHOME_LOCK:
        job = _REHOME_JOBS.get(job_id)
        return dict(job) if job is not None else None


def _start_rehome_job(
    root: Path,
    *,
    card_id: str,
    target_room: str,
    target_subdir: str,
    reason: str,
) -> dict[str, object]:
    """Run a file-card rehome on a daemon thread; the tray polls the job.

    The move itself rides the governed loop (task start → verify → finish, or
    abandon + scope rollback), so it can take minutes while the test suite
    runs; the HTTP answer is just the job handle.
    """
    from ag2c.rehome import rehome_file_card

    job_id = uuid.uuid4().hex[:12]
    with _REHOME_LOCK:
        _REHOME_JOBS[job_id] = {"job": job_id, "state": "running", "card": card_id, "targetRoom": target_room}

    def run_tray_rehome() -> None:
        try:
            result = rehome_file_card(
                root,
                card_id=card_id,
                target_room=target_room,
                target_subdir=target_subdir,
                actor="tray",
                reason=reason,
            )
        except Exception as exc:  # surfaced to the tray on the next poll
            with _REHOME_LOCK:
                _REHOME_JOBS[job_id].update({"state": "failed", "error": str(exc)})
            return
        with _REHOME_LOCK:
            _REHOME_JOBS[job_id].update({"state": "done", "result": result})

    threading.Thread(target=run_tray_rehome, daemon=True).start()
    return _rehome_job(job_id) or {"job": job_id, "state": "running"}


def _canonical_guard(root: Path) -> dict[str, object]:
    """Watchdog: is the canonical checkout dirty outside any open task window?

    Runs `git status` plus a task-table scan, so it is TTL-cached — the digest
    endpoint itself stays subprocess-free for its every-few-seconds polling.
    """
    import time

    key = str(root)
    now = time.monotonic()
    cached = _GUARD_CACHE.get(key)
    if cached and now - cached[0] < _GUARD_TTL_S:
        return dict(cached[1])
    guard: dict[str, object] = {"canonicalDirty": False, "openTasks": 0}
    try:
        from ag2c.config import discover_manifest, load_manifest
        from ag2c.gitops import status_entries
        from ag2c.tasks import TERMINAL_TASK_STATES, task_records

        guard["canonicalDirty"] = bool(status_entries(root))
        manifest = load_manifest(discover_manifest(root), project_root=root)
        guard["openTasks"] = sum(
            1 for task in task_records(root, manifest=manifest) if task.get("state") not in TERMINAL_TASK_STATES
        )
    except Exception:  # watchdog must never break the digest endpoint
        guard["error"] = True
    _GUARD_CACHE[key] = (now, dict(guard))
    return guard


def _project_digest(root: Path) -> dict[str, object]:
    """Cheap fingerprint of everything the tray displays: git HEAD plus the
    governance state files (policy, ledger, journal, census). File IO only —
    no subprocess — so the tray can poll it every few seconds. The guard field
    is separately TTL-cached because it needs a git subprocess."""
    import hashlib

    from ag2c.config import discover_manifest, load_manifest
    from ag2c.gitops import repository_root
    from ag2c.households import census_path
    from ag2c.journal import journal_path

    root = repository_root(root)
    parts: list[str] = []

    def _file_part(path: Path) -> None:
        try:
            stat = path.stat()
        except OSError:
            parts.append(f"{path.name}:missing")
            return
        parts.append(f"{path.name}:{stat.st_mtime_ns}:{stat.st_size}")

    git_dir = root / ".git"
    head = git_dir / "HEAD"
    if head.is_file():
        ref = head.read_text(encoding="utf-8", errors="replace").strip()
        parts.append(f"HEAD:{ref}")
        if ref.startswith("ref:"):
            ref_file = git_dir / ref[4:].strip()
            if ref_file.is_file():
                parts.append(f"ref:{ref_file.read_text(encoding='utf-8', errors='replace').strip()}")
            else:
                _file_part(git_dir / "packed-refs")
    manifest = load_manifest(discover_manifest(root), project_root=root)
    for path in (
        manifest.policy_path,
        manifest.ledger_path,
        journal_path(manifest),
        census_path(manifest),
        manifest.path.parent / "audit-state.json",
    ):
        _file_part(path)
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()
    return {"digest": digest, "version": __version__, "guard": _canonical_guard(root)}


def serve_desktop(*, port: int, token: str, on_ready: Callable[[int], object] | None = None) -> int:
    if not 1 <= port <= 65535:
        raise AG2CError("desktop port must be between 1 and 65535")
    if len(token) < 24:
        raise AG2CError("desktop session token is too short")
    from ag2c.storage import ensure_portable_archive

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
