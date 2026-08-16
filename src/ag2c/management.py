from __future__ import annotations

from pathlib import Path
from typing import Any

from .enrollment import activation_status, setup_project
from .errors import AG2CError
from .gitops import git, repository_root, status_entries
from .harnesses import harness_status
from .storage import project_records, unregister_project
from .tasks import evidence


def project_status(start: Path) -> dict[str, Any]:
    root = repository_root(start)
    status = activation_status(root)
    agents = harness_status()
    report: dict[str, Any] | None = None
    evidence_error: str | None = None
    try:
        report = evidence(root)
    except (AG2CError, OSError, ValueError) as exc:
        evidence_error = str(exc)
    tasks = report.get("tasks", []) if report else []
    completed = [item for item in tasks if item.get("state") == "completed"]
    active = [item for item in tasks if item.get("state") == "active"]
    last = completed[0] if completed else (tasks[0] if tasks else None)
    dirty = status_entries(root)
    entry_ready = any(bool(item.get("integrated")) for item in agents)
    delivery_enforced = bool(status.get("managed"))
    agent_observed = any(item.get("management_result") == "successful" for item in completed)
    issues = list(status.get("issues", []))
    if evidence_error:
        issues.append(f"evidence: {evidence_error}")
    if dirty:
        issues.append("canonical worktree has uncommitted changes")
    if not entry_ready:
        issues.append("no supported AI harness has a current AG2C Skill")
    if delivery_enforced and entry_ready and not dirty:
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
        "completed_tasks": len(completed),
        "last_task": last,
        "ledger_valid": bool(report and report.get("ledger_valid")),
        "coverage": report.get("coverage") if report else None,
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
                    "managed": False,
                    "issues": ["project folder is unavailable"],
                    "entry_ready": False,
                    "delivery_enforced": False,
                    "agent_observed": False,
                    "agents": harness_status(),
                    "active_tasks": 0,
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
                "managed": False,
                "issues": [str(exc)],
                "entry_ready": False,
                "delivery_enforced": False,
                "agent_observed": False,
                "agents": harness_status(),
                "active_tasks": 0,
                "completed_tasks": 0,
                "last_task": None,
                "ledger_valid": False,
            }
        result.append({**record, **current})
    order = {"attention": 0, "inactive": 1, "missing": 2, "protected": 3}
    return sorted(result, key=lambda item: (order.get(str(item.get("state")), 9), str(item.get("name", "")).lower()))


def add_project(path: Path) -> dict[str, Any]:
    setup_project(path)
    return project_status(path)


def repair_and_check_project(path: Path) -> dict[str, Any]:
    setup_project(path)
    return project_status(path)


def stop_managing(path: Path, *, remove_data: bool = False) -> dict[str, Any]:
    root = repository_root(path)
    status = activation_status(root)
    activation = status.get("activation", {})
    expected = str(Path(str(status.get("store"))) / "state" / "hooks") if status.get("store") else ""
    actual = str(git(root, "config", "--get", "core.hooksPath", check=False)).strip()
    if expected and Path(actual).resolve() == Path(expected).resolve():
        previous = str(activation.get("previous_hooks_path", "")) if isinstance(activation, dict) else ""
        if previous:
            git(root, "config", "core.hooksPath", previous)
        else:
            git(root, "config", "--unset-all", "core.hooksPath", check=False)
    result = unregister_project(root, remove_data=remove_data)
    result["previous_evidence_kept"] = not remove_data
    return result
