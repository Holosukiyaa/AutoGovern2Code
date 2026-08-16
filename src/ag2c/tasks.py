from __future__ import annotations

import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .checks import run_checks
from .config import load_manifest, load_policy
from .enrollment import AGENTS_BLOCK, IGNORE_BLOCK, activation_status
from .errors import AG2CError
from .gitops import (
    change_digest,
    changed_paths,
    current_branch,
    git,
    head,
    repository_root,
    status_entries,
)
from .index import build_index, index_path
from .ledger import append_event, read_events, verify_ledger
from .slicer import compile_slice

TASK_SCHEMA = "ag2c.task.v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _task_path(canonical: Path, task_id: str) -> Path:
    return canonical / ".ag2c" / "state" / "tasks" / f"{task_id}.json"


def _load_task(canonical: Path, task_id: str) -> dict[str, Any]:
    path = _task_path(canonical, task_id)
    try:
        task = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AG2CError(f"unknown AG2C task: {task_id}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise AG2CError(f"cannot read AG2C task {task_id}: {exc}") from exc
    if not isinstance(task, dict) or task.get("schema") != TASK_SCHEMA:
        raise AG2CError(f"invalid AG2C task record: {path}")
    return task


def _task_id(goal: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", goal.lower()).strip("-")[:32] or "change"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{slug}-{secrets.token_hex(2)}"


def _record_intervention(
    canonical: Path,
    manifest,
    task: dict[str, Any],
    kind: str,
    detail: dict[str, Any],
) -> None:
    intervention = {"occurred_at": _now(), "kind": kind, **detail}
    task.setdefault("interventions", []).append(intervention)
    event = append_event(manifest.ledger_path, "governance-intervention", {"task_id": task["id"], **intervention})
    intervention["ledger_event_digest"] = event["event_digest"]
    _atomic_json(_task_path(canonical, str(task["id"])), task)


def _canonical_manifest(canonical: Path):
    manifest = load_manifest(canonical / ".ag2c" / "manifest.json")
    return manifest, load_policy(manifest)


def _matching_event(manifest, digest: str, event_type: str, task_id: str) -> dict[str, Any] | None:
    event = next((item for item in read_events(manifest.ledger_path) if item.get("event_digest") == digest), None)
    if event is None or event.get("event_type") != event_type or event.get("payload", {}).get("task_id") != task_id:
        return None
    return event


def _verification_evidence_valid(manifest, task: dict[str, Any], verification: dict[str, Any]) -> bool:
    event = _matching_event(
        manifest,
        str(verification.get("ledger_event_digest", "")),
        "task-verification",
        str(task["id"]),
    )
    if event is None:
        return False
    payload = event["payload"]
    expected = {
        "task_id": task["id"],
        "attempt": verification.get("attempt"),
        "occurred_at": verification.get("occurred_at"),
        "passed": verification.get("passed"),
        "changed_paths": verification.get("changed_paths"),
        "change_digest": verification.get("change_digest"),
        "slice_digest": verification.get("slice_digest"),
        "route_state": verification.get("route_state"),
        "checker_results": verification.get("checker_results"),
        "acceptance": verification.get("acceptance"),
        "check_ledger_event_digest": verification.get("check_ledger_event_digest"),
    }
    if payload != expected:
        return False
    check_event = _matching_event(
        manifest,
        str(verification.get("check_ledger_event_digest", "")),
        "check-run",
        str(task["id"]),
    )
    if check_event is None:
        return False
    actual_results = [
        {"id": item.get("id"), "stage": item.get("stage"), "status": item.get("status"), "exit_code": item.get("exit_code")}
        for item in check_event["payload"].get("results", [])
    ]
    return (
        actual_results == verification.get("checker_results")
        and check_event["payload"].get("slice_digest") == verification.get("slice_digest")
    )


def _start_evidence_valid(manifest, task: dict[str, Any]) -> bool:
    event = _matching_event(
        manifest,
        str(task.get("start_ledger_event_digest", "")),
        "task-started",
        str(task["id"]),
    )
    if event is None:
        return False
    return event["payload"] == {
        "task_id": task["id"],
        "goal": task.get("goal"),
        "source_head": task.get("source", {}).get("head"),
        "source_branch": task.get("source", {}).get("branch"),
        "worktree": task.get("worktree", {}).get("path"),
        "worktree_branch": task.get("worktree", {}).get("branch"),
        "slice_digest": task.get("route", {}).get("slice_digest"),
        "route_state": task.get("route", {}).get("state"),
    }


def start_task(
    start: Path,
    *,
    goal: str,
    path_specs: list[str],
    contract_specs: list[str],
    all_mode: bool = False,
    task_id: str | None = None,
    worktree_root: Path | None = None,
) -> dict[str, Any]:
    root = repository_root(start)
    status = activation_status(root)
    canonical = Path(status["canonical_root"])
    if root != canonical:
        raise AG2CError(f"start AG2C tasks from the canonical worktree: {canonical}")
    if not status["managed"]:
        raise AG2CError("AG2C is not active:\n- " + "\n- ".join(status["issues"]))
    goal = goal.strip()
    if not goal:
        raise AG2CError("AG2C requires a concrete task goal")
    dirty = status_entries(canonical)
    if dirty:
        raise AG2CError("canonical worktree is dirty; AG2C will not start: " + ", ".join(dirty))
    if not path_specs and not contract_specs and not all_mode:
        raise AG2CError("AG2C requires exact paths/contracts or conservative --all before work begins")
    manifest, policy = _canonical_manifest(canonical)
    build_index(manifest, policy, index_path(manifest))
    entry_slice = compile_slice(
        manifest,
        policy,
        path_specs=path_specs,
        contract_specs=contract_specs,
        goal=goal,
        all_mode=all_mode,
    )
    source_head = head(canonical)
    source_branch = current_branch(canonical)
    task_id = task_id or _task_id(goal)
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", task_id):
        raise AG2CError("task id must contain only lowercase letters, digits, dots, underscores, and hyphens")
    record_path = _task_path(canonical, task_id)
    if record_path.exists():
        raise AG2CError(f"AG2C task already exists: {task_id}")
    configured_root = os.environ.get("AG2C_WORKTREE_ROOT")
    base = worktree_root or (Path(configured_root) if configured_root else canonical.parent / ".ag2c-worktrees")
    worktree = (base.resolve() / manifest.project_id / task_id).resolve()
    try:
        worktree.relative_to(canonical)
    except ValueError:
        pass
    else:
        raise AG2CError("AG2C task worktree must be outside the canonical project")
    if worktree.exists():
        raise AG2CError(f"task worktree already exists: {worktree}")
    branch = f"ag2c/{task_id}"
    worktree.parent.mkdir(parents=True, exist_ok=True)
    git(canonical, "worktree", "add", "-b", branch, str(worktree), source_head)
    task: dict[str, Any] = {
        "schema": TASK_SCHEMA,
        "id": task_id,
        "state": "active",
        "goal": goal,
        "created_at": _now(),
        "source": {"root": str(canonical), "branch": source_branch, "head": source_head},
        "worktree": {"path": str(worktree), "branch": branch},
        "entry": {"paths": path_specs, "contracts": contract_specs, "all": all_mode},
        "route": {
            "state": entry_slice["route"]["state"],
            "slice_digest": entry_slice["slice_digest"],
            "fallback_reasons": entry_slice["route"]["fallback_reasons"],
            "checker_ids": [item["id"] for item in entry_slice["check_plan"]],
        },
        "interventions": [],
        "verifications": [],
    }
    _atomic_json(record_path, task)
    marker = worktree / ".ag2c" / "state" / "active-task.json"
    _atomic_json(marker, {"schema": TASK_SCHEMA, "task_id": task_id, "canonical_root": str(canonical)})
    event = append_event(
        manifest.ledger_path,
        "task-started",
        {
            "task_id": task_id,
            "goal": task["goal"],
            "source_head": source_head,
            "source_branch": source_branch,
            "worktree": str(worktree),
            "worktree_branch": branch,
            "slice_digest": entry_slice["slice_digest"],
            "route_state": entry_slice["route"]["state"],
        },
    )
    task["start_ledger_event_digest"] = event["event_digest"]
    _atomic_json(record_path, task)
    return task


def _task_from_worktree(start: Path) -> tuple[Path, dict[str, Any]]:
    root = repository_root(start)
    marker_path = root / ".ag2c" / "state" / "active-task.json"
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AG2CError("this is not an active AG2C task worktree") from exc
    canonical = Path(str(marker.get("canonical_root", ""))).resolve()
    task = _load_task(canonical, str(marker.get("task_id", "")))
    if Path(task["worktree"]["path"]).resolve() != root:
        raise AG2CError("task record does not own this worktree")
    if current_branch(root) != task["worktree"]["branch"]:
        raise AG2CError("task worktree is on a different branch than its AG2C record")
    return canonical, task


def _under(path: str, root: str) -> bool:
    normalized = path.replace("\\", "/").strip("/")
    normalized_root = root.replace("\\", "/").strip("/")
    if normalized_root in {"", ".", "**"}:
        return True
    return normalized == normalized_root or normalized.startswith(normalized_root + "/")


def _changed_specs(manifest, paths: list[str]) -> tuple[list[str], list[str]]:
    specs: list[str] = []
    unmanaged: list[str] = []
    for path in paths:
        matched = False
        for target in manifest.targets:
            target_prefix = target.path.replace("\\", "/").strip("./")
            relative = path
            if target_prefix:
                if not _under(path, target_prefix):
                    continue
                relative = path[len(target_prefix):].strip("/")
            if any(_under(relative, governed_root) for governed_root in target.governed_roots):
                specs.append(f"{target.target_id}:{relative}")
                matched = True
                break
        if not matched:
            unmanaged.append(path)
    return sorted(set(specs)), sorted(unmanaged)


def verify_task(start: Path) -> dict[str, Any]:
    worktree = repository_root(start)
    canonical, task = _task_from_worktree(worktree)
    if task["state"] != "active":
        raise AG2CError(f"task is not active: {task['id']} ({task['state']})")
    canonical_manifest, _ = _canonical_manifest(canonical)
    formal_dirty = status_entries(canonical)
    if formal_dirty:
        _record_intervention(canonical, canonical_manifest, task, "canonical-write-blocked", {"paths": formal_dirty})
        raise AG2CError("canonical worktree changed during the task; refusing verification")
    if head(canonical) != task["source"]["head"]:
        _record_intervention(
            canonical,
            canonical_manifest,
            task,
            "canonical-head-diverged",
            {"expected": task["source"]["head"], "actual": head(canonical)},
        )
        raise AG2CError("canonical HEAD changed during the task; start a new task from the current branch")
    actual_paths = changed_paths(worktree, task["source"]["head"])
    if not actual_paths:
        raise AG2CError("task worktree has no changes to verify")
    protected = [path for path in actual_paths if path.startswith(".ag2c/")]
    agents = worktree / "AGENTS.md"
    if not agents.is_file() or AGENTS_BLOCK.rstrip() not in agents.read_text(encoding="utf-8"):
        protected.append("AGENTS.md")
    ignore = worktree / ".gitignore"
    if not ignore.is_file() or IGNORE_BLOCK.rstrip() not in ignore.read_text(encoding="utf-8"):
        protected.append(".gitignore")
    if protected:
        _record_intervention(canonical, canonical_manifest, task, "governance-mutation-blocked", {"paths": protected})
        raise AG2CError("ordinary tasks cannot modify AG2C governance controls: " + ", ".join(protected))
    manifest = load_manifest(worktree / ".ag2c" / "manifest.json")
    policy = load_policy(manifest)
    path_specs, unmanaged = _changed_specs(manifest, actual_paths)
    if unmanaged:
        _record_intervention(canonical, canonical_manifest, task, "ungoverned-change-blocked", {"paths": unmanaged})
        raise AG2CError("changed paths are outside the governed project: " + ", ".join(unmanaged))
    build_index(manifest, policy, index_path(manifest))
    actual_slice = compile_slice(
        manifest,
        policy,
        path_specs=path_specs,
        contract_specs=list(task["entry"]["contracts"]),
        goal=str(task["goal"]),
        all_mode=bool(task["entry"]["all"]),
    )
    initial_paths = set(task["entry"]["paths"])
    expanded = sorted(set(path_specs) - initial_paths)
    if expanded and not any(
        item.get("kind") == "scope-expanded" and item.get("paths") == expanded
        for item in task.get("interventions", [])
    ):
        _record_intervention(canonical, canonical_manifest, task, "scope-expanded", {"paths": expanded})
    before_check_digest = change_digest(worktree, task["source"]["head"])
    report = run_checks(
        manifest,
        policy,
        actual_slice,
        all_mode=bool(task["entry"]["all"]),
        ledger_path=canonical_manifest.ledger_path,
        task_id=str(task["id"]),
    )
    after_check_digest = change_digest(worktree, task["source"]["head"])
    checker_mutated_change = before_check_digest != after_check_digest
    passed = (
        bool(report["results"])
        and all(item["status"] == "passed" for item in report["results"])
        and not checker_mutated_change
    )
    verification = {
        "attempt": len(task["verifications"]) + 1,
        "occurred_at": _now(),
        "passed": passed,
        "changed_paths": actual_paths,
        "change_digest": after_check_digest,
        "slice_digest": actual_slice["slice_digest"],
        "route_state": actual_slice["route"]["state"],
        "checker_results": [
            {"id": item["id"], "stage": item["stage"], "status": item["status"], "exit_code": item["exit_code"]}
            for item in report["results"]
        ],
        "acceptance": report["acceptance"],
        "check_ledger_event_digest": report["ledger_event_digest"],
    }
    verification_event = append_event(
        canonical_manifest.ledger_path,
        "task-verification",
        {"task_id": task["id"], **verification},
    )
    verification["ledger_event_digest"] = verification_event["event_digest"]
    prior_failure = any(not item.get("passed", False) for item in task["verifications"])
    task["verifications"].append(verification)
    _atomic_json(_task_path(canonical, str(task["id"])), task)
    if checker_mutated_change:
        _record_intervention(
            canonical,
            canonical_manifest,
            task,
            "checker-mutated-change",
            {"attempt": verification["attempt"]},
        )
    elif passed and prior_failure:
        _record_intervention(
            canonical,
            canonical_manifest,
            task,
            "ai-correction-proven",
            {"failed_attempts": sum(not item.get("passed", False) for item in task["verifications"][:-1]), "passing_attempt": verification["attempt"]},
        )
    elif not passed:
        _record_intervention(
            canonical,
            canonical_manifest,
            task,
            "verification-failed",
            {"attempt": verification["attempt"], "failed_checkers": [item["id"] for item in report["results"] if item["status"] != "passed"]},
        )
    return {"task_id": task["id"], "passed": passed, "verification": verification}


def finish_task(start: Path, task_id: str, *, message: str) -> dict[str, Any]:
    root = repository_root(start)
    status = activation_status(root)
    canonical = Path(status["canonical_root"])
    if root != canonical:
        raise AG2CError(f"finish AG2C tasks from the canonical worktree: {canonical}")
    if not status["managed"]:
        raise AG2CError("AG2C is not active")
    task = _load_task(canonical, task_id)
    if task["state"] != "active":
        raise AG2CError(f"task is not active: {task_id} ({task['state']})")
    manifest, _ = _canonical_manifest(canonical)
    if not _start_evidence_valid(manifest, task):
        raise AG2CError("task start evidence is missing or inconsistent")
    if not task["verifications"] or not task["verifications"][-1]["passed"]:
        raise AG2CError("task has no passing final verification")
    if not _verification_evidence_valid(manifest, task, task["verifications"][-1]):
        raise AG2CError("passing verification evidence is missing or inconsistent")
    worktree = Path(task["worktree"]["path"]).resolve()
    if not worktree.is_dir():
        raise AG2CError(f"task worktree is missing: {worktree}")
    if repository_root(worktree) != worktree or current_branch(worktree) != task["worktree"]["branch"]:
        raise AG2CError("task worktree identity no longer matches its AG2C record")
    dirty = status_entries(canonical)
    if dirty:
        manifest, _ = _canonical_manifest(canonical)
        _record_intervention(canonical, manifest, task, "merge-blocked-canonical-dirty", {"paths": dirty})
        raise AG2CError("canonical worktree is dirty; refusing merge")
    if head(canonical) != task["source"]["head"] or current_branch(canonical) != task["source"]["branch"]:
        raise AG2CError("canonical branch or HEAD changed; refusing merge")
    current_digest = change_digest(worktree, task["source"]["head"])
    if current_digest != task["verifications"][-1]["change_digest"]:
        raise AG2CError("task changed after verification; run `ag2c task verify` again")
    if status_entries(worktree):
        git(worktree, "add", "--all")
        git(worktree, "commit", "-m", message)
    elif head(worktree) == task["source"]["head"]:
        raise AG2CError("task worktree has no commit or changes to integrate")
    task_commit = head(worktree)
    if status_entries(worktree):
        raise AG2CError("task worktree is not clean after commit")
    committed_digest = change_digest(worktree, task["source"]["head"])
    if committed_digest != current_digest:
        _record_intervention(
            canonical,
            manifest,
            task,
            "commit-hook-mutated-change",
            {"verified_change_digest": current_digest, "committed_change_digest": committed_digest},
        )
        raise AG2CError("commit hooks changed the verified bytes; run `ag2c task verify` again")
    git(canonical, "merge", "--ff-only", task["worktree"]["branch"])
    manifest, policy = _canonical_manifest(canonical)
    build_index(manifest, policy, index_path(manifest))
    task["state"] = "completed"
    task["completed_at"] = _now()
    task["result"] = {
        "commit": task_commit,
        "merged_head": head(canonical),
        "merge": "fast-forward",
        "verified_change_digest": current_digest,
    }
    event = append_event(
        manifest.ledger_path,
        "task-completed",
        {"task_id": task_id, **task["result"], "intervention_count": len(task["interventions"])},
    )
    task["result"]["ledger_event_digest"] = event["event_digest"]
    _atomic_json(_task_path(canonical, task_id), task)
    cleanup = "completed"
    try:
        git(canonical, "worktree", "remove", str(worktree))
        git(canonical, "branch", "-d", task["worktree"]["branch"])
    except AG2CError as exc:
        cleanup = f"pending: {exc}"
    task["cleanup"] = cleanup
    _atomic_json(_task_path(canonical, task_id), task)
    return task


def task_record(start: Path, task_id: str) -> dict[str, Any]:
    canonical = Path(activation_status(start)["canonical_root"])
    return _load_task(canonical, task_id)


def task_records(start: Path) -> list[dict[str, Any]]:
    canonical = Path(activation_status(start)["canonical_root"])
    directory = canonical / ".ag2c" / "state" / "tasks"
    records = [_load_task(canonical, path.stem) for path in directory.glob("*.json")] if directory.is_dir() else []
    return sorted(records, key=lambda item: str(item.get("created_at", "")), reverse=True)


def evidence(start: Path, task_id: str | None = None) -> dict[str, Any]:
    status = activation_status(start)
    canonical = Path(status["canonical_root"])
    manifest, _ = _canonical_manifest(canonical)
    ledger_errors = verify_ledger(manifest.ledger_path)
    events = read_events(manifest.ledger_path) if not ledger_errors else []
    events_by_digest = {str(event["event_digest"]): event for event in events}
    records = [task_record(canonical, task_id)] if task_id else task_records(canonical)
    summaries = []
    for task in records:
        verifications = task.get("verifications", [])
        references: list[tuple[str, str]] = []
        references.append((str(task.get("start_ledger_event_digest", "")), "task-started"))
        references.extend(
            (str(item.get("ledger_event_digest", "")), "governance-intervention")
            for item in task.get("interventions", [])
        )
        references.extend(
            (str(item.get("ledger_event_digest", "")), "task-verification")
            for item in verifications
        )
        references.extend(
            (str(item.get("check_ledger_event_digest", "")), "check-run")
            for item in verifications
        )
        if task.get("result"):
            references.append((str(task["result"].get("ledger_event_digest", "")), "task-completed"))
        evidence_complete = True
        for digest, expected_type in references:
            event = events_by_digest.get(digest)
            payload = event.get("payload", {}) if event else {}
            if (
                not digest
                or event is None
                or event.get("event_type") != expected_type
                or payload.get("task_id") != task["id"]
            ):
                evidence_complete = False
                break
        start_valid = not ledger_errors and _start_evidence_valid(manifest, task)
        if not start_valid:
            evidence_complete = False
        if evidence_complete:
            for intervention in task.get("interventions", []):
                event = events_by_digest.get(str(intervention.get("ledger_event_digest", "")))
                expected = {
                    "task_id": task["id"],
                    **{key: value for key, value in intervention.items() if key != "ledger_event_digest"},
                }
                if event is None or event.get("payload") != expected:
                    evidence_complete = False
                    break
        if evidence_complete and any(
            not _verification_evidence_valid(manifest, task, verification)
            for verification in verifications
        ):
            evidence_complete = False
        if evidence_complete and task.get("result"):
            result_event = events_by_digest.get(str(task["result"].get("ledger_event_digest", "")))
            expected_result = {
                "task_id": task["id"],
                **{key: value for key, value in task["result"].items() if key != "ledger_event_digest"},
                "intervention_count": len(task.get("interventions", [])),
            }
            if result_event is None or result_event.get("payload") != expected_result:
                evidence_complete = False
        verified = bool(
            verifications
            and verifications[-1].get("passed")
            and _verification_evidence_valid(manifest, task, verifications[-1])
        )
        completed = task["state"] == "completed" and bool(task.get("result"))
        summaries.append(
            {
                "id": task["id"],
                "goal": task["goal"],
                "state": task["state"],
                "managed": start_valid,
                "management_result": "successful" if completed and verified and evidence_complete else "incomplete",
                "evidence_complete": evidence_complete,
                "route_state": task["route"]["state"],
                "interventions": task.get("interventions", []),
                "verification_attempts": len(verifications),
                "verifications": verifications,
                "verified": verified,
                "result": task.get("result"),
                "cleanup": task.get("cleanup"),
            }
        )
    return {"project": manifest.project_id, "managed": status["managed"], "ledger_valid": not ledger_errors, "ledger_errors": ledger_errors, "tasks": summaries}
