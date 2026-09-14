"""Tray host helpers with no GUI toolkit import."""

from __future__ import annotations

import json
import os
import secrets
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ag2c.util import hidden_process_kwargs

FILTERS = (
    ("", "全部"),
    ("placeholder", "占位"),
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

ISSUE_LABELS = {
    "canonical worktree has uncommitted changes": "正式工作副本有未提交改动",
    "governance is stopped": "治理已关闭",
    "open task worktree has diverged from the canonical branch": "施工副本已和正式分支分叉",
    "project is not enrolled": "还没有纳入治理",
    "AG2C Git guard is not active": "交付门禁未接通",
}

SPAN_LABELS = {"none": "未打标", "folder": "整夹一张", "file": "一文件一张"}
QUIET_STATUS = frozenset({"", "在册", "current"})
PROBLEM_STATUS = frozenset(
    {"占位", "开工", "黑盒", "过期", "废弃未清", "未普查", "未验收", "AI正在写", "无主", "重复认领", "文档"}
)

FLAG_LABELS = {
    "placeholder": "占位",
    "document": "文档",
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

HARNESS_LABELS = {
    "codex": "Codex",
    "claude": "Claude Code",
    "cursor": "Cursor",
    "agents": "通用 Agent Skills",
}

HARNESS_STATE_LABELS = {
    "ready": "入口已就绪",
    "skill-missing": "缺少 Skill",
    "not-detected": "未检测",
}

PRODUCT_LABELS = {
    "checked": "产品验收已通过",
    "blocked": "规则过期，不能当产品通过",
    "incomplete": "产品验收还没跑完",
    "undeclared": "产品验收未登记",
}

WORKTREE_LIFE_LABELS = {
    "in-progress": "正在改",
    "verified-unmerged": "改完了没合并",
    "verified-stale": "验证后有新改动",
    "diverged": "已分叉",
    "missing": "副本丢失",
    "completed": "已合并",
    "abandoned": "已经废弃",
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


def is_directory_household(card: dict[str, Any]) -> bool:
    if card.get("jurisdiction") or card.get("household"):
        return True
    span = card.get("span")
    return bool(span) and str(span) not in {"", "none"}


def card_problem_status(card: dict[str, Any]) -> str:
    """User-facing exception badge. 在册 is the default healthy state and stays blank."""
    status = first_flag_label(card) or text(card, "status")
    if status in QUIET_STATUS:
        return ""
    if status in PROBLEM_STATUS:
        return status
    return ""


def card_list_badge(card: dict[str, Any]) -> str:
    problem = card_problem_status(card)
    if is_directory_household(card):
        if problem and problem != "文档":
            return problem
        return SPAN_LABELS.get(_card_span(card), "未打标")
    return problem


def card_list_label(title: str, card: dict[str, Any], count: int, *, ordinal: int = 0, ordinal_label: str = "") -> str:
    label = ordinal_label or (str(ordinal) if ordinal > 0 else "")
    head = f"{label}. {title}" if label else title
    parts = [head]
    badge = card_list_badge(card)
    if badge:
        parts.append(badge)
    if is_directory_household(card) and count > 0:
        parts.append(f"{count} 个文件")
    return "  ·  ".join(parts)


def first_flag_label(node: dict[str, Any]) -> str:
    label = text(node, "statusLabel")
    if label:
        return label
    flags = node.get("flags")
    if isinstance(flags, list) and flags:
        from ag2c.graph import STATUS_TAG_LABELS, status_tag_key

        return STATUS_TAG_LABELS[status_tag_key(str(item) for item in flags)]
    return text(node, "role")


def state_label(state: str) -> str:
    return STATE_LABELS.get(state, "未生效")


def issue_label(issue: str) -> str:
    text = str(issue or "").strip()
    if text in ISSUE_LABELS:
        return ISSUE_LABELS[text]
    if text.startswith("canonical worktree is dirty"):
        files = text.split(":", 1)[-1].strip() if ":" in text else text
        return "正式工作副本有未提交改动，请先提交或暂存：\n" + files
    return text


def _task_line(task: dict[str, Any] | None) -> str:
    if not isinstance(task, dict):
        return ""
    delivery = task.get("delivery") if isinstance(task.get("delivery"), dict) else {}
    return str(delivery.get("outcome") or delivery.get("request") or task.get("goal") or "").strip()


def _open_worktrees(details: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows = details.get("worktrees") if isinstance(details, dict) and isinstance(details.get("worktrees"), list) else []
    return [row for row in rows if isinstance(row, dict) and str(row.get("state") or "") in {"active", "verified"}]


def skill_prompt_text(project_root: str = "") -> str:
    from ag2c.harnesses import skill_entry_prompt

    return skill_entry_prompt(project=Path(project_root) if project_root else Path.cwd())


def mcp_entry_text(project_root: str = "") -> str:
    from ag2c.mcp_server import mcp_connect_prompt

    del project_root
    text = mcp_connect_prompt()
    return text if text.endswith("\n") else text + "\n"


_MCP_HEALTH_TTL_S = 5.0
_mcp_health_cache: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}


def mcp_health_snapshot(
    *,
    handshake: bool = False,
    home: Path | None = None,
    cwd: str | Path | None = None,
    managed: bool | None = None,
) -> dict[str, Any]:
    """UI 侧健康快照：短 TTL 缓存。

    项目栏每帧都会调用（文件树窗口打开时）；底层 mcp_health 的
    mcp_launch_spec 在 worktree 场景要做 manifest 发现（git 子进程，
    Windows 上约 60ms），逐帧调用会把 165fps 拖到 15fps。健康状态
    变化是秒级事件，5s 缓存足够新鲜。
    """
    key = (
        bool(handshake),
        str(home) if home is not None else None,
        str(cwd) if cwd is not None else None,
        managed,
    )
    now = time.monotonic()
    hit = _mcp_health_cache.get(key)
    if hit is not None and now - hit[0] < _MCP_HEALTH_TTL_S:
        return hit[1]
    from ag2c.mcp_server import mcp_health

    value = mcp_health(handshake=handshake, home=home, cwd=cwd, managed=managed)
    _mcp_health_cache[key] = (now, value)
    if len(_mcp_health_cache) > 32:
        # 项目切换会产生新 key；兜底清理过期项，避免长时间运行堆积。
        stale = [k for k, (ts, _) in _mcp_health_cache.items() if now - ts >= _MCP_HEALTH_TTL_S]
        for k in stale:
            _mcp_health_cache.pop(k, None)
    return value


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


def preferred_project_root(projects: list[dict[str, Any]]) -> str:
    for wanted in ("attention", "protected", "stopped", "inactive"):
        for row in projects:
            if str(row.get("state") or "") != wanted:
                continue
            root = text(row, "root")
            if root:
                return root
    return ""


AUDIT_LIMIT = 800


def audit_log_path() -> Path:
    override = os.environ.get("AG2C_AUDIT_LOG", "").strip()
    if override:
        return Path(override)
    return Path(os.environ.get("TEMP", ".") or ".") / "ag2c-audit.log"


def append_audit(lines: list[str], action: str, where: str, detail: str = "", *, limit: int = AUDIT_LIMIT) -> str:
    """Append one operator action to an in-memory ring and the audit log file."""
    frac = time.time()
    stamp = time.strftime("%H:%M:%S", time.localtime(frac)) + f".{int(frac * 1000) % 1000:03d}"
    detail = " ".join(str(detail or "").split())
    if len(detail) > 400:
        detail = detail[:397] + "..."
    line = f"{stamp}  {action}  {where}"
    if detail:
        line += f"  {detail}"
    lines.append(line)
    extra = len(lines) - limit
    if extra > 0:
        del lines[:extra]
    try:
        with audit_log_path().open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass
    return line


def selected_root_after_list(projects: list[dict[str, Any]], selected: str) -> str:
    """Keep the current selection if it is still listed; otherwise pick a live root."""
    roots = {text(row, "root") for row in projects if isinstance(row, dict)}
    if selected and selected in roots:
        return selected
    return preferred_project_root(projects)


def digest_triggers_reload(previous: str, current: str) -> bool:
    """Reload dashboard/tree when a later digest differs from the one already shown."""
    return bool(current) and bool(previous) and previous != current


def row_key(node: dict[str, Any], fallback: str = "") -> str:
    return text(node, "id") or text(node, "path") or fallback


def claim_owners(node: dict[str, Any]) -> list[str]:
    return [item for item in string_list(node, "coveredBy") if item]


def claim_label(node: dict[str, Any]) -> str:
    labels = string_list(node, "claimLabels")
    if len(labels) > 1:
        return "重复认领"
    if len(labels) == 1:
        return labels[0]
    owners = claim_owners(node)
    if len(owners) > 1:
        return "重复认领"
    if len(owners) == 1:
        return owners[0]
    return "未认领"


def ancestor_prefixes(rel: str) -> list[str]:
    parts = [part for part in rel.replace("\\", "/").split("/") if part]
    return ["/".join(parts[:index]) for index in range(1, len(parts))]


def card_for_owner(cards: list[dict[str, Any]], owner: str) -> dict[str, Any] | None:
    for card in cards:
        if text(card, "kind") != "knowledge":
            continue
        if text(card, "title") == owner or text(card, "id") == owner:
            return card
    return None


def cards_for_owners(cards: list[dict[str, Any]], owners: list[str]) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    seen: set[str] = set()
    for owner in owners:
        card = card_for_owner(cards, owner)
        if card is None:
            continue
        key = row_key(card, text(card, "title"))
        if key in seen:
            continue
        seen.add(key)
        matched.append(card)
    return matched


def _card_path_prefixes(card: dict[str, Any]) -> list[str]:
    prefixes: list[str] = []
    raw = text(card, "path")
    for chunk in raw.replace("、", ",").split(","):
        path = file_relpath({"path": chunk}) if ":" in chunk else chunk.replace("\\", "/").strip("/")
        if path and path != ".":
            prefixes.append(path)
    return prefixes


def _clean_scope_path(value: str) -> str:
    path = value.replace("\\", "/").split(":", 1)[-1].lstrip("/").rstrip("*").rstrip("/")
    return path


def _card_scope_records(card: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for scope in card.get("scopes") or []:
        if isinstance(scope, dict):
            records.append(scope)
    household = card.get("household")
    if isinstance(household, dict):
        for scope in household.get("scopes") or []:
            if isinstance(scope, dict):
                records.append(scope)
    return records


def _rel_under_card(rel: str, card: dict[str, Any]) -> bool:
    includes: list[str] = []
    excludes: list[str] = []
    for scope in _card_scope_records(card):
        includes.extend(_clean_scope_path(str(item)) for item in (scope.get("include") or scope.get("includes") or []) if item)
        excludes.extend(_clean_scope_path(str(item)) for item in (scope.get("exclude") or scope.get("excludes") or []) if item)
    if not includes:
        includes.extend(_clean_scope_path(chunk) for chunk in text(card, "path").replace("、", ",").split(",") if chunk.strip())
    needle = rel.replace("\\", "/").lstrip("/")
    if not any(path and (needle == path or needle.startswith(path + "/")) for path in includes):
        return False
    return not any(path and (needle == path or needle.startswith(path + "/")) for path in excludes)


def files_for_card(files: list[tuple[str, dict[str, Any]]], card: dict[str, Any]) -> list[str]:
    return [rel for rel, node in files if file_owned_by_card(node, card)]


def peer_rels(files: list[tuple[str, dict[str, Any]]], node: dict[str, Any]) -> list[str]:
    owners = claim_owners(node)
    if len(owners) != 1:
        return []
    owner = owners[0]
    return [rel for rel, other in files if claim_owners(other) == [owner]]


def _card_span(card: dict[str, Any]) -> str:
    jurisdiction = card.get("jurisdiction") if isinstance(card.get("jurisdiction"), dict) else {}
    household = card.get("household") if isinstance(card.get("household"), dict) else {}
    nested = household.get("jurisdiction") if isinstance(household.get("jurisdiction"), dict) else {}
    raw = card.get("span") or jurisdiction.get("span") or nested.get("span") or "none"
    return str(raw or "none")


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
            with urllib.request.urlopen(request, timeout=300) as response:
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


def register_app(executable: str, version: str = "0.11.0") -> None:
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


_JOB_HANDLES: list[int] = []  # keep job handles alive for the process lifetime


def _bind_kill_on_close(process) -> None:
    """Assign the child to a kill-on-close Job so Windows ends it when this process dies.

    Without this, a crashed or force-killed tray leaves `ag2c desktop serve` running
    as an orphan. Best-effort: any failure leaves the child as-is.
    """
    if os.name != "nt":
        return
    pid = getattr(process, "pid", None)
    if not isinstance(pid, int):  # mocked Popen in tests
        return
    try:
        import ctypes
        from ctypes import wintypes

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
                ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_uint64)
                for name in (
                    "ReadOperationCount",
                    "WriteOperationCount",
                    "OtherOperationCount",
                    "ReadTransferCount",
                    "WriteTransferCount",
                    "OtherTransferCount",
                )
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
        JobObjectExtendedLimitInformation = 9
        PROCESS_SET_QUOTA = 0x0100
        PROCESS_TERMINATE = 0x0001

        kernel32 = ctypes.windll.kernel32
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.OpenProcess.restype = wintypes.HANDLE
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            job, JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)
        ):
            kernel32.CloseHandle(job)
            return
        child = kernel32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
        if not child:
            kernel32.CloseHandle(job)
            return
        try:
            if kernel32.AssignProcessToJobObject(job, child):
                _JOB_HANDLES.append(job)  # closing the handle would kill the child now
            else:
                kernel32.CloseHandle(job)
        finally:
            kernel32.CloseHandle(child)
    except Exception:
        return


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
    process = subprocess.Popen(**kwargs)
    _bind_kill_on_close(process)
    return process


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

from .tray_inspect import inspect_fields, empty_inspect, inspect_file, inspect_card, _exact_file_card, focus_file, focus_card, build_row_cache, coverage_rows, file_tree_children, coverage_scroll_key, project_gate_rows, file_owned_by_card, design_summary_for_file, _file_card_summary
