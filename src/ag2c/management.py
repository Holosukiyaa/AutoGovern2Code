from __future__ import annotations

import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .config import discover_manifest, load_manifest, load_policy
from . import __version__
from .enrollment import activation_status, align_engine, needs_engine_align, setup_project, stored_tool_version
from .errors import AG2CError
from .gitops import git, repository_root, status_entries
from .harnesses import harness_status
from .index import findings as index_findings
from .index import index_path, summary as index_summary, verify_freshness
from .knowledge import knowledge_status
from .ledger import ledger_summary
from .storage import (
    GOVERNANCE_STOPPED,
    MANIFEST_CONFIG_KEY,
    PROJECT_KEY_CONFIG_KEY,
    find_project_record,
    project_records,
    registered_manifest,
    set_project_governance,
    unregister_project,
)
from .tasks import evidence, list_tasks
from .util import default_data_root


def _unavailable_project(record: dict[str, Any], agents: list[dict[str, Any]], *, issue: str, state: str) -> dict[str, Any]:
    root = Path(str(record.get("root", "")))
    return {
        **record,
        "name": record.get("name") or root.name,
        "root": str(root),
        "state": state,
        "governance": record.get("governance") or "active",
        "managed": False,
        "issues": [issue],
        "entry_ready": False,
        "delivery_enforced": False,
        "agent_observed": False,
        "agents": agents,
        "active_tasks": 0,
        "verified_tasks": 0,
        "open_tasks": 0,
        "abandoned_tasks": 0,
        "completed_tasks": 0,
        "last_task": None,
        "ledger_valid": False,
        "coverage": None,
        "product": None,
        "pending_count": 0,
        "pending": [],
    }


def _compose_project_card(
    *,
    root: Path,
    record: dict[str, Any] | None,
    status: dict[str, Any],
    agents: list[dict[str, Any]],
    dirty: list[str],
    tasks: list[dict[str, Any]],
    pending_items: list[dict[str, Any]],
    evidence_error: str | None = None,
    report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    governance = str((record or {}).get("governance") or "active")
    completed = [item for item in tasks if item.get("state") == "completed"]
    active = [item for item in tasks if item.get("state") == "active"]
    verified = [item for item in tasks if item.get("state") == "verified"]
    abandoned = [item for item in tasks if item.get("state") == "abandoned"]
    last = completed[0] if completed else (tasks[0] if tasks else None)
    entry_ready = True
    delivery_enforced = bool(status.get("managed"))
    agent_observed = any(item.get("management_result") == "successful" for item in completed) or (
        bool(completed) and report is None
    )
    if governance == GOVERNANCE_STOPPED:
        issues = ["governance is stopped"]
        diverged: list[str] = []
    else:
        issues = list(status.get("issues", []))
        if evidence_error:
            issues.append(f"evidence: {evidence_error}")
        if dirty:
            issues.append("canonical worktree has uncommitted changes")
        diverged = [
            str(item.get("id") or "")
            for item in tasks
            if item.get("state") in {"active", "verified"} and (item.get("worktree") or {}).get("lifecycle") == "diverged"
        ]
        if diverged:
            issues.append("open task worktree has diverged from the canonical branch")
    if governance == GOVERNANCE_STOPPED:
        state = "stopped"
    elif delivery_enforced and not dirty and not diverged:
        state = "protected"
    elif delivery_enforced:
        state = "attention"
    else:
        state = "inactive"
    return {
        "project_id": (report or {}).get("project") or root.name,
        "name": root.name,
        "root": str(root),
        "state": state,
        "governance": governance,
        "managed": delivery_enforced,
        "issues": issues,
        "dirty": bool(dirty),
        "dirty_paths": dirty,
        "store": status.get("store"),
        "entry_ready": entry_ready,
        "delivery_enforced": delivery_enforced,
        "agent_observed": agent_observed,
        "agents": agents,
        "active_tasks": len(active),
        "verified_tasks": len(verified),
        "open_tasks": len(active) + len(verified),
        "abandoned_tasks": len(abandoned),
        "completed_tasks": len(completed),
        "last_task": last,
        "ledger_valid": bool(report and report.get("ledger_valid")),
        "coverage": report.get("coverage") if report else None,
        "product": report.get("product") if report else ((last or {}).get("product") if last else None),
        "pending_count": len(pending_items),
        "pending": pending_items,
        "engine_version": __version__,
        "tool_version": stored_tool_version(root),
    }


def _pending_items(root: Path) -> list[dict[str, Any]]:
    from .govern import stored_pending

    try:
        return list((stored_pending(root) or {}).get("items") or [])
    except (AG2CError, OSError, ValueError):
        return []


def project_list_item(start: Path, *, agents: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    root = repository_root(start)
    status = activation_status(root)
    if agents is None:
        agents = harness_status()
    record = find_project_record(root)
    try:
        tasks = list_tasks(root)
    except (AG2CError, OSError, ValueError):
        tasks = []
    try:
        dirty = status_entries(root)
    except (AG2CError, OSError, ValueError):
        dirty = []
    return _compose_project_card(
        root=root,
        record=record,
        status=status,
        agents=agents,
        dirty=dirty,
        tasks=tasks,
        pending_items=_pending_items(root),
    )


def project_status(start: Path, *, agents: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    root = repository_root(start)
    status = activation_status(root)
    if agents is None:
        agents = harness_status()
    record = find_project_record(root)
    report: dict[str, Any] | None = None
    evidence_error: str | None = None
    try:
        report = evidence(root, verify_local=False, activation=status)
    except (AG2CError, OSError, ValueError) as exc:
        evidence_error = str(exc)
    tasks = report.get("tasks", []) if report else []
    try:
        dirty = status_entries(root)
    except (AG2CError, OSError, ValueError):
        dirty = []
    return _compose_project_card(
        root=root,
        record=record,
        status=status,
        agents=agents,
        dirty=dirty,
        tasks=tasks,
        pending_items=_pending_items(root),
        evidence_error=evidence_error,
        report=report,
    )


# Each project card costs several git subprocesses; the tray asks for the list
# twice at startup (projects, then align) and after every action. A short TTL
# makes the second read free while mutations invalidate explicitly.
_MANAGED_CACHE: tuple[float, list[dict[str, Any]]] | None = None
_MANAGED_LOCK = threading.Lock()
MANAGED_CACHE_TTL_SECONDS = 5.0


def invalidate_managed_cache() -> None:
    global _MANAGED_CACHE
    with _MANAGED_LOCK:
        _MANAGED_CACHE = None


def managed_projects() -> list[dict[str, Any]]:
    global _MANAGED_CACHE
    with _MANAGED_LOCK:
        cached = _MANAGED_CACHE
    if cached is not None and time.monotonic() - cached[0] < MANAGED_CACHE_TTL_SECONDS:
        return [dict(item) for item in cached[1]]
    agents = harness_status()
    records = project_records()

    def build(record: dict[str, Any]) -> dict[str, Any]:
        root = Path(str(record.get("root", "")))
        if not root.is_dir():
            return _unavailable_project(record, agents, issue="project folder is unavailable", state="missing")
        try:
            current = project_list_item(root, agents=agents)
        except (AG2CError, OSError, ValueError) as exc:
            current = _unavailable_project(record, agents, issue=str(exc), state="inactive")
        return {**record, **current}

    if len(records) > 1:
        # git subprocess waits release the GIL, so projects build in parallel.
        with ThreadPoolExecutor(max_workers=min(4, len(records))) as pool:
            result = list(pool.map(build, records))
    else:
        result = [build(record) for record in records]
    order = {"attention": 0, "protected": 1, "stopped": 2, "inactive": 3, "missing": 4}
    result = sorted(result, key=lambda item: (order.get(str(item.get("state")), 9), str(item.get("name", "")).lower()))
    with _MANAGED_LOCK:
        _MANAGED_CACHE = (time.monotonic(), result)
    return [dict(item) for item in result]


def align_managed_projects() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for record in project_records():
        root = Path(str(record.get("root", "")))
        if not root.is_dir():
            continue
        if str(record.get("governance") or "active") == GOVERNANCE_STOPPED:
            continue
        try:
            if not needs_engine_align(root):
                continue
            result.append(align_engine(root))
        except (AG2CError, OSError, ValueError) as exc:
            result.append(
                {
                    "action": "failed",
                    "root": str(root),
                    "name": record.get("name") or root.name,
                    "from_version": stored_tool_version(root) or "unknown",
                    "to_version": __version__,
                    "resliced": False,
                    "error": str(exc),
                }
            )
    if result:
        invalidate_managed_cache()
    return result


def add_project(path: Path) -> dict[str, Any]:
    setup_project(path)
    invalidate_managed_cache()
    return project_status(path)


def details_fingerprint(root: Path) -> str:
    try:
        head = str(git(root, "rev-parse", "HEAD", check=False)).strip()
    except AG2CError:
        head = ""
    try:
        porcelain = str(git(root, "status", "--porcelain", check=False))
    except AG2CError:
        porcelain = ""
    payload = f"{root.resolve()}\n{head}\n{porcelain}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _details_cache_file(root: Path) -> Path:
    digest = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:20]
    return default_data_root() / "cache" / f"details-{digest}.json"


def _read_details_cache(root: Path) -> tuple[dict[str, Any] | None, str]:
    path = _details_cache_file(root)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None, ""
    if not isinstance(raw, dict) or not isinstance(raw.get("details"), dict):
        return None, ""
    return raw["details"], str(raw.get("fingerprint") or "")


def _write_details_cache(root: Path, fingerprint: str, details: dict[str, Any]) -> None:
    path = _details_cache_file(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"fingerprint": fingerprint, "details": details}, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
    except OSError:
        pass


def _empty_details(project: dict[str, Any]) -> dict[str, Any]:
    return {
        "project": project,
        "available": False,
        "manifest": None,
        "cards": [],
        "relations": [],
        "contracts": [],
        "checkers": [],
        "index": {"current": False, "errors": [], "summary": None, "findings": []},
        "knowledge": [],
        "pending": {"items": []},
        "worktrees": [],
        "ledger": None,
        "journals": [],
    }


def project_details(path: Path, *, refresh: bool = False) -> dict[str, Any]:
    start = path.expanduser().resolve()
    if not start.is_dir():
        record = find_project_record(start) or {"root": str(start), "name": start.name}
        return _empty_details(_unavailable_project(record, harness_status(), issue="project folder is unavailable", state="missing"))
    try:
        root = repository_root(start)
    except AG2CError as exc:
        record = find_project_record(start) or {"root": str(start), "name": start.name}
        return _empty_details(_unavailable_project(record, harness_status(), issue=str(exc), state="inactive"))
    fingerprint = details_fingerprint(root)
    if not refresh:
        cached, cached_fp = _read_details_cache(root)
        if cached is not None and cached_fp == fingerprint:
            result = cached
        else:
            result = _compute_project_details(root)
            _write_details_cache(root, fingerprint, result)
    else:
        result = _compute_project_details(root)
        _write_details_cache(root, fingerprint, result)
    _overlay_audit_status(root, result)
    _overlay_patrol_status(root, result)
    _overlay_hazard_status(root, result)
    _overlay_token_status(root, result)
    return result


def _overlay_status(root: Path, result: dict[str, Any], *, key: str, produce, fallback_factory) -> None:
    """状态叠加通用控制流：现算不缓存；异常降级为 fallback_factory()。

    四兄弟（patrol/hazard/token/audit）曾各自复制这套控制流——危房名单
    校准后它们占了查重区一半。produce 接收 manifest 返回报告；降级载荷
    用工厂每次现造（原实现每次异常都生成全新字面量，浅拷贝会共享嵌套
    可变值——监管 reject 的教训）。
    """
    if not result.get("available"):
        return
    try:
        manifest_path = discover_manifest(root)
        if manifest_path is None:
            return
        manifest = load_manifest(manifest_path, project_root=root)
        result[key] = produce(manifest)
    except (AG2CError, OSError, ValueError):
        result[key] = fallback_factory()


def _patrol_overlay(manifest) -> dict[str, Any]:
    from .patrol import patrol_report

    return patrol_report(manifest)


def _hazard_overlay(manifest) -> dict[str, Any]:
    from .hazard import hazard_report

    return hazard_report(manifest, load_policy(manifest))


def _token_overlay(manifest) -> dict[str, Any]:
    from .token import token_report

    return token_report(manifest)


def _audit_overlay(manifest) -> dict[str, Any]:
    from .audit import audit_status

    return audit_status(manifest, load_policy(manifest))


def _overlay_patrol_status(root: Path, result: dict[str, Any]) -> None:
    """巡逻叙事（演习/拦截）：现算不缓存。"""
    _overlay_status(root, result, key="patrol", produce=_patrol_overlay,
                    fallback_factory=lambda: {"drills": {}, "interceptions": {"total": 0, "in_window": 0, "recent": []}})


def _overlay_hazard_status(root: Path, result: dict[str, Any]) -> None:
    """危房名单（变异存活/查重/预算/陈旧）：现算不缓存。"""
    _overlay_status(root, result, key="hazards", produce=_hazard_overlay,
                    fallback_factory=lambda: {"schema": "ag2c.hazard.v1", "hazards": [], "counts": {}})


def _overlay_token_status(root: Path, result: dict[str, Any]) -> None:
    """治理 token 成本（会话税/引导注入/verify 返工折算成钱）：现算不缓存。"""
    _overlay_status(root, result, key="token", produce=_token_overlay,
                    fallback_factory=lambda: {"schema": "ag2c.token.v1", "cost_usd": 0.0, "month_cost_usd": 0.0, "month_tokens": 0, "top_rework": []})


def _overlay_audit_status(root: Path, result: dict[str, Any]) -> None:
    """随机抽查状态：现算（不随 details 缓存），且只有这条用户侧
    路径会触发生成——verify / run_checks 不读取、不展示抽查计划。"""
    _overlay_status(root, result, key="audit", produce=_audit_overlay,
                    fallback_factory=lambda: {"pending": [], "due": False, "days_since": None})


def _compute_project_details(root: Path) -> dict[str, Any]:
    status = project_list_item(root)
    result: dict[str, Any] = {
        "project": status,
        "available": False,
        "manifest": None,
        "cards": [],
        "relations": [],
        "contracts": [],
        "checkers": [],
        "index": {"current": False, "errors": [], "summary": None, "findings": []},
        "knowledge": [],
        "pending": {"items": []},
        "worktrees": [],
        "ledger": None,
        "journals": [],
    }
    try:
        manifest_path = discover_manifest(root) if status.get("managed") else registered_manifest(root)
    except AG2CError:
        manifest_path = registered_manifest(root)
    if manifest_path is None or not Path(manifest_path).is_file():
        return result
    result["available"] = True
    manifest = load_manifest(manifest_path, project_root=root)
    policy = load_policy(manifest)
    result["manifest"] = {
        "path": str(manifest.path),
        "project_id": manifest.project_id,
        "project_root": str(manifest.project_root),
        "targets": [
            {
                "id": target.target_id,
                "path": target.path,
                "governed_roots": list(target.governed_roots),
                "excludes": list(target.excludes),
            }
            for target in manifest.targets
        ],
    }
    result["cards"] = [
        {
            "id": card.card_id,
            "type": card.card_type,
            "title": card.title,
            "summary": card.summary,
            "scopes": [
                {
                    "target": scope.target_id,
                    "include": list(scope.includes),
                    "exclude": list(scope.excludes),
                    "ownership": scope.ownership,
                }
                for scope in card.scopes
            ],
            "checkers": list(card.checkers),
            "references": list(card.references),
            "jurisdiction": card.jurisdiction,
        }
        for card in policy.cards
    ]
    result["relations"] = [
        {"source": relation.source, "type": relation.relation_type, "target": relation.target}
        for relation in policy.relations
    ]
    result["contracts"] = [
        {
            "target": contract.target_id,
            "id": contract.contract_id,
            "version": contract.version,
            "boundary": contract.boundary,
            "scenarios": list(contract.scenarios),
        }
        for contract in policy.contracts
    ]
    result["checkers"] = [
        {
            "id": checker.checker_id,
            "stage": checker.stage,
            "target": checker.target_id,
            "command": list(checker.command),
            "cwd": checker.cwd,
            "timeout": checker.timeout,
            "implementation": checker.implementation,
        }
        for checker in policy.checkers
    ]
    current_errors = verify_freshness(manifest, policy, index_path(manifest))
    result["index"]["errors"] = current_errors
    if not current_errors:
        result["index"]["current"] = True
        result["index"]["summary"] = index_summary(index_path(manifest))
        result["index"]["findings"] = index_findings(index_path(manifest))
    result["knowledge"] = knowledge_status(manifest, policy)
    from .govern import pending_updates

    try:
        result["pending"] = pending_updates(root)
    except (AG2CError, OSError, ValueError):
        result["pending"] = {"items": []}
    result["project"]["pending_count"] = len(result["pending"].get("items") or [])
    result["project"]["pending"] = result["pending"].get("items") or []
    try:
        result["worktrees"] = list_tasks(root)
    except (AG2CError, OSError, ValueError):
        result["worktrees"] = []
    try:
        result["ledger"] = ledger_summary(manifest.ledger_path)
    except (AG2CError, OSError, ValueError) as exc:
        result["ledger"] = {"error": str(exc)}
    from .journal import list_journals

    try:
        result["journals"] = list_journals(root)
    except (AG2CError, OSError, ValueError):
        result["journals"] = []
    from ag2c_gui.graph import build_governance_graph

    from .households import census_report, file_latest_commits

    try:
        result["census"] = census_report(manifest, policy)
    except (AG2CError, OSError, ValueError) as exc:
        result["census"] = {"error": str(exc), "households": [], "directories": []}
    from .checks import baseline_debt

    try:
        result["baseline_debt"] = baseline_debt(manifest)
    except (AG2CError, OSError, ValueError):
        result["baseline_debt"] = {"total": 0, "target": 0, "over": False}
    result["file_history"] = {}
    try:
        revisions = (result.get("census") or {}).get("revisions") or {}
        for target in manifest.targets:
            head = str((revisions.get(target.target_id) or {}).get("commit") or "")
            result["file_history"][target.target_id] = file_latest_commits(manifest.target_root(target.target_id), head)
    except (AG2CError, OSError, TypeError, ValueError):
        result["file_history"] = {}

    result["graph"] = build_governance_graph(result)
    return result


def repair_and_check_project(path: Path) -> dict[str, Any]:
    setup_project(path)
    invalidate_managed_cache()
    return project_status(path)


def _detach_enforcement(root: Path) -> None:
    status = activation_status(root)
    store = status.get("store")
    if not store:
        manifest = registered_manifest(root)
        store = str(manifest.parent) if manifest is not None else ""
    expected = str(Path(str(store)) / "state" / "hooks") if store else ""
    actual = str(git(root, "config", "--get", "core.hooksPath", check=False)).strip()
    activation = status.get("activation", {})
    if expected and actual and Path(actual).resolve() == Path(expected).resolve():
        previous = str(activation.get("previous_hooks_path", "")) if isinstance(activation, dict) else ""
        if previous:
            git(root, "config", "core.hooksPath", previous)
        else:
            git(root, "config", "--unset-all", "core.hooksPath", check=False)
    git(root, "config", "--local", "--unset-all", MANIFEST_CONFIG_KEY, check=False)
    git(root, "config", "--local", "--unset-all", PROJECT_KEY_CONFIG_KEY, check=False)


def stop_managing(path: Path, *, remove_data: bool = False) -> dict[str, Any]:
    root = repository_root(path)
    _detach_enforcement(root)
    invalidate_managed_cache()
    if remove_data:
        result = unregister_project(root, remove_data=True)
        result["previous_evidence_kept"] = False
        result["uninstalled"] = True
        result["governance"] = None
        return result
    record = set_project_governance(root, GOVERNANCE_STOPPED)
    return {
        "root": str(root),
        "key": record["key"],
        "registered": True,
        "governance": GOVERNANCE_STOPPED,
        "data_removed": False,
        "previous_evidence_kept": True,
        "uninstalled": False,
    }


def uninstall_project(path: Path) -> dict[str, Any]:
    return stop_managing(path, remove_data=True)
