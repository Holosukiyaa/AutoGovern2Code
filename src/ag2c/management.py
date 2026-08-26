from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import discover_manifest, load_manifest, load_policy
from .enrollment import activation_status, setup_project
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


def project_status(start: Path) -> dict[str, Any]:
    root = repository_root(start)
    status = activation_status(root)
    agents = harness_status()
    record = find_project_record(root)
    governance = str((record or {}).get("governance") or "active")
    report: dict[str, Any] | None = None
    evidence_error: str | None = None
    if governance != GOVERNANCE_STOPPED:
        try:
            report = evidence(root)
        except (AG2CError, OSError, ValueError) as exc:
            evidence_error = str(exc)
    tasks = report.get("tasks", []) if report else []
    completed = [item for item in tasks if item.get("state") == "completed"]
    active = [item for item in tasks if item.get("state") == "active"]
    verified = [item for item in tasks if item.get("state") == "verified"]
    abandoned = [item for item in tasks if item.get("state") == "abandoned"]
    last = completed[0] if completed else (tasks[0] if tasks else None)
    dirty = status_entries(root)
    entry_ready = any(bool(item.get("integrated")) for item in agents)
    delivery_enforced = bool(status.get("managed"))
    agent_observed = any(item.get("management_result") == "successful" for item in completed)
    if governance == GOVERNANCE_STOPPED:
        issues = ["governance is stopped"]
    else:
        issues = list(status.get("issues", []))
        if evidence_error:
            issues.append(f"evidence: {evidence_error}")
        if dirty:
            issues.append("canonical worktree has uncommitted changes")
        diverged = [
            item["id"]
            for item in tasks
            if item.get("state") in {"active", "verified"} and (item.get("worktree") or {}).get("lifecycle") == "diverged"
        ]
        if diverged:
            issues.append("open task worktree has diverged from the canonical branch")
        if not entry_ready:
            issues.append("no supported AI harness has a current AG2C Skill")
    from .govern import stored_pending

    pending_items = list((stored_pending(root) or {}).get("items") or [])
    if governance == GOVERNANCE_STOPPED:
        state = "stopped"
    elif delivery_enforced and entry_ready and not dirty and not diverged:
        state = "protected"
    elif delivery_enforced:
        state = "attention"
    else:
        state = "inactive"
    return {
        "project_id": report.get("project") if report else root.name,
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
        "product": report.get("product") if report else None,
        "pending_count": len(pending_items),
        "pending": pending_items,
    }


def managed_projects() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for record in project_records():
        root = Path(str(record.get("root", "")))
        if not root.is_dir():
            result.append(
                {
                    **record,
                    "name": record.get("name") or root.name,
                    "state": "missing",
                    "governance": record.get("governance") or "active",
                    "managed": False,
                    "issues": ["project folder is unavailable"],
                    "entry_ready": False,
                    "delivery_enforced": False,
                    "agent_observed": False,
                    "agents": harness_status(),
                    "active_tasks": 0,
                    "verified_tasks": 0,
                    "open_tasks": 0,
                    "abandoned_tasks": 0,
                    "completed_tasks": 0,
                    "last_task": None,
                    "ledger_valid": False,
                }
            )
            continue
        try:
            current = project_status(root)
        except (AG2CError, OSError, ValueError) as exc:
            current = {
                **record,
                "name": record.get("name") or root.name,
                "root": str(root),
                "state": "inactive",
                "governance": record.get("governance") or "active",
                "managed": False,
                "issues": [str(exc)],
                "entry_ready": False,
                "delivery_enforced": False,
                "agent_observed": False,
                "agents": harness_status(),
                "active_tasks": 0,
                "verified_tasks": 0,
                "open_tasks": 0,
                "abandoned_tasks": 0,
                "completed_tasks": 0,
                "last_task": None,
                "ledger_valid": False,
            }
        result.append({**record, **current})
    order = {"attention": 0, "inactive": 1, "stopped": 2, "missing": 3, "protected": 4}
    return sorted(result, key=lambda item: (order.get(str(item.get("state")), 9), str(item.get("name", "")).lower()))


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
