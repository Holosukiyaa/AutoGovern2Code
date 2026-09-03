from __future__ import annotations

import hashlib
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
    project_store,
    registered_manifest,
    registry_path,
    set_project_governance,
    unregister_project,
)
from .tasks import evidence, list_tasks


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
    entry_ready = any(bool(item.get("integrated")) for item in agents)
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
        if not entry_ready:
            issues.append("no supported AI harness has a current AG2C Skill")
    if governance == GOVERNANCE_STOPPED:
        state = "stopped"
    elif delivery_enforced and entry_ready and not dirty and not diverged:
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


def managed_projects() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    agents = harness_status()
    for record in project_records():
        root = Path(str(record.get("root", "")))
        if not root.is_dir():
            result.append(_unavailable_project(record, agents, issue="project folder is unavailable", state="missing"))
            continue
        try:
            current = project_list_item(root, agents=agents)
        except (AG2CError, OSError, ValueError) as exc:
            current = _unavailable_project(record, agents, issue=str(exc), state="inactive")
        result.append({**record, **current})
    order = {"attention": 0, "inactive": 1, "stopped": 2, "missing": 3, "protected": 4}
    return sorted(result, key=lambda item: (order.get(str(item.get("state")), 9), str(item.get("name", "")).lower()))


def _mtime_token(path: Path) -> str:
    try:
        stat = path.stat()
    except OSError:
        return "0"
    return f"{int(stat.st_mtime)}:{stat.st_size}"


def _directory_token(path: Path) -> str:
    if not path.is_dir():
        return "0"
    marks = [_mtime_token(path)]
    try:
        children = list(path.iterdir())
    except OSError:
        return marks[0]
    for child in children:
        if child.is_file():
            marks.append(f"{child.name}:{_mtime_token(child)}")
        elif child.is_dir() and child.name in {"tasks", "state"}:
            marks.append(f"{child.name}:{_directory_token(child)}")
    return ";".join(sorted(marks))


def projects_revision() -> dict[str, str]:
    parts = [_mtime_token(registry_path())]
    for record in project_records():
        root = Path(str(record.get("root", "")))
        parts.append(str(record.get("key", "")))
        parts.append(str(record.get("governance", "")))
        if root.is_dir():
            try:
                parts.append(str(git(root, "rev-parse", "HEAD", check=False)).strip())
                parts.append("\0".join(status_entries(root)))
            except (AG2CError, OSError, ValueError):
                parts.append("git-unavailable")
            try:
                parts.append(_directory_token(project_store(root, record.get("key"))))
            except (AG2CError, OSError, TypeError, ValueError):
                parts.append("store-unavailable")
        else:
            parts.append("missing")
    return {"revision": hashlib.sha256("\n".join(parts).encode("utf-8", errors="replace")).hexdigest()}


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
    return result


def add_project(path: Path) -> dict[str, Any]:
    setup_project(path)
    return project_status(path)


def project_details(path: Path) -> dict[str, Any]:
    root = repository_root(path)
    status = project_status(root)
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
    return result


def repair_and_check_project(path: Path) -> dict[str, Any]:
    setup_project(path)
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
