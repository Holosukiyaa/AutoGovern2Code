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


def card_list_label(title: str, card: dict[str, Any], count: int, *, ordinal: int = 0) -> str:
    head = f"{ordinal}. {title}" if ordinal > 0 else title
    parts = [head]
    badge = card_list_badge(card)
    if badge:
        parts.append(badge)
    if is_directory_household(card) and count > 0:
        parts.append(f"{count} 个文件")
    return "  ·  ".join(parts)


def lineage_subtitle(node: dict[str, Any]) -> str:
    replaced = text(node, "replaced_by")
    if replaced:
        return "已被 " + replaced + " 替换"
    kind = text(node, "kind")
    status = text(node, "status")
    tag = text(node, "statusTag")
    if kind == "module":
        return status
    if kind != "knowledge":
        return status
    if node.get("nested") and node.get("cards"):
        return status
    if tag in {"placeholder", "exploring", "opaque", "stale", "abandoned", "unreviewed", "writing", "undeclared"}:
        return status
    if tag == "document":
        return "文档"
    label = text(node, "spanLabel")
    if label:
        return label
    span = text(node, "span")
    if span in SPAN_LABELS:
        return SPAN_LABELS[span]
    return ""


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
    from .harnesses import skill_entry_prompt

    return skill_entry_prompt(project=Path(project_root) if project_root else Path.cwd())


def mcp_entry_text(project_root: str = "") -> str:
    from .mcp_server import mcp_connect_prompt

    del project_root
    text = mcp_connect_prompt()
    return text if text.endswith("\n") else text + "\n"


def mcp_health_snapshot(
    *,
    handshake: bool = False,
    home: Path | None = None,
    cwd: str | Path | None = None,
    managed: bool | None = None,
) -> dict[str, Any]:
    from .mcp_server import mcp_health

    return mcp_health(handshake=handshake, home=home, cwd=cwd, managed=managed)


def project_gate_rows(
    project: dict[str, Any] | None,
    details: dict[str, Any] | None = None,
    *,
    mcp: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Always-on operator strip: MCP entry, observed records, construction."""
    if not project:
        return []
    managed = project.get("delivery_enforced")
    health = mcp if mcp is not None else mcp_health_snapshot(
        handshake=False,
        cwd=text(project, "root") or None,
        managed=None if managed is None else bool(managed),
    )
    if managed is False and health.get("ok"):
        health = {**health, "ok": False, "status": "broken", "label": "MCP 异常", "error": "Git hook is off"}
    entry_value = str(health.get("label") or "MCP 异常")
    entry_warn = not bool(health.get("ok"))
    completed = int(project.get("completed_tasks") or 0)
    last_line = _task_line(project.get("last_task") if isinstance(project.get("last_task"), dict) else None)
    if completed:
        records_value = f"{completed} 次入库"
        if last_line:
            records_value += " · " + last_line
    else:
        records_value = "尚未观察"
    open_rows = _open_worktrees(details)
    flags: list[str] = []
    for row in open_rows:
        life = str((row.get("worktree") or {}).get("lifecycle") or "")
        state = str(row.get("state") or "")
        if life == "diverged":
            flags.append("已分叉")
        elif life == "missing":
            flags.append("副本丢失")
        elif state == "verified" or life in {"verified-unmerged", "verified-stale"}:
            flags.append("改完了没合并")
    unique = list(dict.fromkeys(flags))
    if unique:
        construction_value = f"{len(unique)} 个异常 · " + "、".join(unique)
        construction_warn = True
    elif open_rows:
        construction_value = f"{len(open_rows)} 个进行中"
        construction_warn = False
    elif int(project.get("open_tasks") or 0) > 0:
        construction_value = f"{int(project['open_tasks'])} 个进行中"
        construction_warn = False
    else:
        construction_value = "没有进行中的施工"
        construction_warn = False
    return [
        {"id": "gate", "label": "AI 入口", "value": entry_value, "warn": entry_warn},
        {"id": "records", "label": "实际记录", "value": records_value, "warn": False},
        {"id": "worktrees", "label": "施工", "value": construction_value, "warn": construction_warn},
    ]


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


def inspect_fields(node: dict[str, Any]) -> dict[str, Any]:
    who = text(node, "coverageLabel") or "、".join(string_list(node, "coveredBy"))
    floors = "、".join(string_list(node, "floors")) or text(node, "floorLabel")
    when = text(node, "lastCommit") or text(node, "changedAt")
    role = text(node, "roleLabel") or first_flag_label(node)
    title = text(node, "title") or text(node, "path") or "点文件树或知识卡"
    flags = node.get("flags") if isinstance(node.get("flags"), list) else []
    placeholder = text(node, "statusTag") == "placeholder" or "placeholder" in {str(item) for item in flags}
    return {
        "mode": text(node, "kind") or "folder",
        "title": title,
        "status": first_flag_label(node),
        "summary": text(node, "summary"),
        "who": who or "—",
        "floors": floors or "—",
        "when": when or "—",
        "role": role or "—",
        "path": text(node, "path") or "—",
        "claim": "",
        "peers": [],
        "files": [],
        "cards": [],
        "message": "入学占位，还没有说清这个目录" if placeholder else "",
    }


def empty_inspect(headline: str = "") -> dict[str, Any]:
    return {
        "mode": "empty",
        "title": "点文件树或知识卡",
        "status": headline or "点文件树或知识卡查看归属。",
        "summary": "",
        "claim": "",
        "path": "",
        "peers": [],
        "files": [],
        "cards": [],
        "message": "",
    }


def preferred_project_root(projects: list[dict[str, Any]]) -> str:
    for wanted in ("attention", "protected", "stopped", "inactive"):
        for row in projects:
            if str(row.get("state") or "") != wanted:
                continue
            root = text(row, "root")
            if root:
                return root
    return ""


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


def file_owned_by_card(node: dict[str, Any], card: dict[str, Any]) -> bool:
    rel = file_relpath(node)
    owners = claim_owners(node)
    kind = text(card, "kind")
    card_id = text(card, "id")
    title = text(card, "title") or card_id
    if kind == "knowledge":
        if title in owners or card_id in owners:
            return True
        if text(node, "parentCard") == card_id:
            return True
        if card.get("jurisdiction") or card.get("household") or card.get("span"):
            return _rel_under_card(rel, card)
        return False
    if kind == "gap":
        if owners:
            return False
        prefixes = _card_path_prefixes(card)
        if not prefixes:
            return True
        return any(rel == prefix or rel.startswith(prefix + "/") for prefix in prefixes)
    if kind == "work":
        prefixes = _card_path_prefixes(card)
        return any(rel == prefix or rel.startswith(prefix + "/") or prefix.startswith(rel + "/") for prefix in prefixes)
    return False


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


def _file_card_summary(cards: list[dict[str, Any]], rel: str) -> str:
    for card in cards:
        if text(card, "kind") not in {"", "knowledge"} and text(card, "type") not in {"", "knowledge"}:
            continue
        if card.get("jurisdiction") or card.get("household"):
            continue
        includes: list[str] = []
        for scope in card.get("scopes") or []:
            if not isinstance(scope, dict):
                continue
            includes.extend(str(item) for item in (scope.get("include") or scope.get("includes") or []) if item)
        paths = [item.replace("\\", "/").split(":", 1)[-1].lstrip("/") for item in includes]
        if paths == [rel.replace("\\", "/").lstrip("/")]:
            return text(card, "summary")
    return ""


def design_summary_for_file(rel: str, owner_cards: list[dict[str, Any]], all_cards: list[dict[str, Any]]) -> str:
    if len(owner_cards) != 1:
        return ""
    owner = owner_cards[0]
    household = bool(owner.get("jurisdiction") or owner.get("household") or owner.get("span"))
    if not household:
        return text(owner, "summary")
    span = _card_span(owner)
    if span == "folder":
        return text(owner, "summary")
    if span == "file":
        return _file_card_summary(all_cards, rel)
    return ""


def inspect_file(
    node: dict[str, Any],
    files: list[tuple[str, dict[str, Any]]],
    cards: list[dict[str, Any]],
) -> dict[str, Any]:
    rel = file_relpath(node)
    owners = claim_owners(node)
    matched = cards_for_owners(cards, owners)
    related: list[dict[str, str]] = []
    seen: set[str] = set()
    for card in matched:
        title = text(card, "title") or text(card, "id")
        key = row_key(card, title)
        if key in seen:
            continue
        seen.add(key)
        related.append({"id": key, "title": title})
    for owner in owners:
        if owner in seen or any(item["title"] == owner for item in related):
            continue
        related.append({"id": owner, "title": owner})
    summary = design_summary_for_file(rel, matched, cards)
    return {
        "mode": "file",
        "title": text(node, "title") or rel.rsplit("/", 1)[-1],
        "status": card_problem_status(node),
        "summary": summary,
        "claim": claim_label(node),
        "path": rel,
        "peers": peer_rels(files, node),
        "files": [],
        "cards": related,
        "message": "未认领" if not owners else "",
    }


def inspect_card(card: dict[str, Any], files: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    governed = files_for_card(files, card)
    flags = card.get("flags") if isinstance(card.get("flags"), list) else []
    placeholder = text(card, "statusTag") == "placeholder" or "placeholder" in {str(item) for item in flags}
    household = is_directory_household(card)
    span = _card_span(card) if household else ""
    if placeholder:
        message = "入学占位，还没有说清这个目录"
    elif governed:
        message = ""
    else:
        message = "这张卡还没有落到文件树上的代码文件"
    show_design = bool(text(card, "summary")) and (not household or span == "folder")
    from .graph import card_abstract, card_detail, lineage_ordinal

    summary = text(card, "summary") if show_design else ""
    title = text(card, "title") or text(card, "id")
    ordinal = lineage_ordinal(card)
    return {
        "mode": "card",
        "title": f"{ordinal}. {title}" if ordinal else title,
        "status": card_problem_status(card),
        "summary": summary,
        "abstract": card_abstract(card) if show_design else "",
        "detail": card_detail(card) if show_design else "",
        "ordinal": ordinal,
        "claim": "",
        "path": "",
        "peers": [],
        "files": governed,
        "cards": [],
        "message": message,
        "span": span if household else None,
        "span_label": SPAN_LABELS.get(span, "未打标") if household else "",
        "card_id": text(card, "id"),
    }


def _exact_file_card(cards: list[dict[str, Any]], rel: str) -> dict[str, Any] | None:
    needle = rel.replace("\\", "/").lstrip("/")
    for card in cards:
        if text(card, "kind") not in {"", "knowledge"} and text(card, "type") not in {"", "knowledge"}:
            continue
        if card.get("jurisdiction") or card.get("household"):
            continue
        includes: list[str] = []
        for scope in card.get("scopes") or []:
            if not isinstance(scope, dict):
                continue
            includes.extend(_clean_scope_path(str(item)) for item in (scope.get("include") or scope.get("includes") or []) if item)
        if includes == [needle]:
            return card
    return None


def focus_file(
    files: list[tuple[str, dict[str, Any]]],
    cards: list[dict[str, Any]],
    rel: str,
) -> dict[str, Any] | None:
    node = next((item for path, item in files if path == rel), None)
    if node is None:
        return None
    owners = claim_owners(node)
    matched = cards_for_owners(cards, owners)
    file_card = _exact_file_card(cards, rel)
    primary = file_card or (matched[0] if matched else None)
    card_keys = {row_key(primary, text(primary, "title"))} if primary else set()
    card_ids = []
    if primary is not None:
        card_ids.append(text(primary, "id") or row_key(primary, text(primary, "title")))
    parent_id = text(node, "parentCard")
    if parent_id and parent_id not in card_ids:
        card_ids.append(parent_id)
    for card in matched:
        ident = text(card, "id") or row_key(card, text(card, "title"))
        if ident and ident not in card_ids:
            card_ids.append(ident)
    prefixes: set[str] = set(ancestor_prefixes(rel))
    primary_key = row_key(primary, text(primary, "title")) if primary else ""
    inspect = inspect_file(node, files, cards)
    inspect["peers"] = []
    return {
        "selected_file": rel,
        "selected_card_key": primary_key,
        "highlight_card_keys": card_keys,
        "inspect_key": row_key(node, rel),
        "inspect": inspect,
        "highlight_paths": {rel} if owners else set(),
        "force_open": prefixes,
        "scroll_card_key": primary_key,
        "scroll_file_key": coverage_scroll_key(files, {rel}),
        "lineage_nav_id": card_ids[0] if card_ids else "",
        "lineage_nav_ids": card_ids,
    }


def card_matching_lineage(cards: list[dict[str, Any]], node: dict[str, Any]) -> dict[str, Any] | None:
    node_id = text(node, "id")
    title = text(node, "title")
    for item in cards:
        if text(item, "id") == node_id or (title and text(item, "title") == title):
            return item
    return None


def focus_card(
    files: list[tuple[str, dict[str, Any]]],
    card: dict[str, Any],
) -> dict[str, Any]:
    governed = files_for_card(files, card)
    prefixes: set[str] = set()
    for path in governed:
        prefixes.update(ancestor_prefixes(path))
    title = text(card, "title") or text(card, "id")
    key = row_key(card, title)
    card_id = text(card, "id") or key
    highlight = set(governed)
    return {
        "selected_file": "",
        "selected_card_key": key,
        "highlight_card_keys": {key},
        "inspect_key": key,
        "inspect": inspect_card(card, files),
        "highlight_paths": highlight,
        "force_open": prefixes,
        "scroll_card_key": key,
        "scroll_file_key": coverage_scroll_key(files, highlight),
        "lineage_nav_id": card_id,
        "lineage_nav_ids": [card_id],
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


def file_tree_children(
    files: list[tuple[str, dict[str, Any]]],
) -> dict[str, list[tuple[str, str, str, dict[str, Any]]]]:
    """Nest files under folder prefixes. Root parent is '' so src/ag2c/a.py can open src."""
    buckets: dict[str, dict[str, tuple[str, str, dict[str, Any]]]] = {}
    for rel, node in files:
        parts = [part for part in rel.replace("\\", "/").split("/") if part]
        if not parts:
            continue
        for index, name in enumerate(parts):
            parent = "/".join(parts[:index])
            prefix = "/".join(parts[: index + 1])
            slot = buckets.setdefault(parent, {})
            if index == len(parts) - 1:
                slot[name] = ("file", prefix, node)
            elif name not in slot or slot[name][0] != "file":
                slot[name] = (
                    "dir",
                    prefix,
                    {"kind": "folder", "title": name, "path": prefix, "summary": "文件夹"},
                )
    tree: dict[str, list[tuple[str, str, str, dict[str, Any]]]] = {}
    for parent, slot in buckets.items():
        items = [(name, kind, prefix, node) for name, (kind, prefix, node) in slot.items()]
        items.sort(key=lambda item: (0 if item[1] == "dir" else 1, item[0].lower()))
        tree[parent] = items
    return tree


def coverage_scroll_key(files: list[tuple[str, dict[str, Any]]], highlight: set[str]) -> str:
    """Tree prefix pinned at the top of the file-tree body for a highlighted coverage."""
    hits = [rel for rel, _node in files if rel in highlight]
    if not hits:
        return ""
    if len(hits) == 1:
        rel = hits[0]
        return rel.rsplit("/", 1)[0] if "/" in rel else rel
    parts_list = [rel.split("/") for rel in hits]
    common: list[str] = []
    for index, piece in enumerate(parts_list[0]):
        if all(len(parts) > index + 1 and parts[index] == piece for parts in parts_list):
            common.append(piece)
        else:
            break
    if common:
        return "/".join(common)
    tree = file_tree_children([(rel, node) for rel, node in files if rel in highlight])

    def walk(parent: str) -> str:
        for _name, kind, prefix, _node in tree.get(parent, []):
            if kind == "file" and prefix in highlight:
                return prefix
            if kind == "dir":
                found = walk(prefix)
                if found:
                    return found
        return ""

    return walk("") or hits[0]


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
