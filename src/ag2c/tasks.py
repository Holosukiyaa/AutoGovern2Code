from __future__ import annotations

import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .checks import run_checks
from .config import discover_manifest, load_manifest, load_policy
from .enrollment import activation_status
from .errors import AG2CError
from .gitops import (
    change_digest,
    changed_paths,
    current_branch,
    git,
    head,
    is_ancestor,
    rebase_worktree,
    repository_root,
    status_entries,
)
from .index import build_index, index_path
from .ledger import append_event, read_events, verify_ledger
from .receipts import (
    build_receipt,
    receipt_path,
    verify_commit_receipt,
    write_receipt,
)
from .slicer import compile_slice
from .storage import git_private_path
from .util import digest_file

TASK_SCHEMA = "ag2c.task.v1"
OPEN_TASK_STATES = frozenset({"active", "verified"})
TERMINAL_TASK_STATES = frozenset({"completed", "abandoned"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _task_path(canonical: Path, task_id: str) -> Path:
    manifest = load_manifest(discover_manifest(canonical))
    return manifest.state_dir / "tasks" / f"{task_id}.json"


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
    manifest = load_manifest(discover_manifest(canonical))
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
        "route": verification.get("route"),
        "route_cards": verification.get("route_cards"),
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
    started_head = task.get("source", {}).get("started_head") or task.get("source", {}).get("head")
    return event["payload"] == {
        "task_id": task["id"],
        "goal": task.get("goal"),
        "source_head": started_head,
        "source_branch": task.get("source", {}).get("started_branch") or task.get("source", {}).get("branch"),
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
    base = worktree_root or (Path(configured_root) if configured_root else manifest.path.parent / "worktrees")
    worktree = (base.resolve() / task_id).resolve()
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
        "source": {
            "root": str(canonical),
            "branch": source_branch,
            "head": source_head,
            "started_head": source_head,
            "started_branch": source_branch,
            "policy_digest": digest_file(policy.path),
            "manifest_digest": digest_file(manifest.path),
        },
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
    marker = git_private_path(worktree, "ag2c-task.json")
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
    from .govern import retrieve_guidance

    return {**task, "guidance": retrieve_guidance(canonical, path_specs=path_specs, contract_specs=contract_specs, goal=goal)}


def _require_open_task(task: dict[str, Any]) -> None:
    state = str(task.get("state", ""))
    if state in TERMINAL_TASK_STATES:
        raise AG2CError(f"task is {state}: {task['id']}")
    if state not in OPEN_TASK_STATES:
        raise AG2CError(f"task is not open: {task['id']} ({state})")


def _remove_task_worktree(canonical: Path, task: dict[str, Any], *, force: bool) -> str:
    worktree = Path(str(task["worktree"]["path"]))
    branch = str(task["worktree"]["branch"])
    try:
        if worktree.exists():
            args = ["worktree", "remove"]
            if force:
                args.append("--force")
            git(canonical, *args, str(worktree))
        git(canonical, "branch", "-D" if force else "-d", branch, check=False)
        return "removed"
    except AG2CError as exc:
        return f"pending: {exc}"


def _worktree_snapshot(canonical: Path, task: dict[str, Any]) -> dict[str, Any]:
    recorded = task.get("worktree") or {}
    path = Path(str(recorded.get("path", "")))
    present = bool(str(recorded.get("path", ""))) and path.is_dir()
    canonical_head = head(canonical)
    source_head = str(task.get("source", {}).get("head", ""))
    diverged = bool(source_head) and canonical_head != source_head
    dirty = False
    bytes_changed = False
    if present:
        try:
            dirty = bool(status_entries(path))
            last_pass = next(
                (item for item in reversed(task.get("verifications", [])) if item.get("passed")),
                None,
            )
            if source_head and last_pass:
                bytes_changed = change_digest(path, source_head) != last_pass.get("change_digest")
        except AG2CError:
            present = False
    state = str(task.get("state", ""))
    if state == "completed":
        lifecycle = "completed"
    elif state == "abandoned":
        lifecycle = "abandoned"
    elif not present:
        lifecycle = "missing"
    elif diverged:
        lifecycle = "diverged"
    elif state == "verified" and bytes_changed:
        lifecycle = "verified-stale"
    elif state == "verified":
        lifecycle = "verified-unmerged"
    else:
        lifecycle = "in-progress"
    return {
        "path": str(recorded.get("path", "")),
        "branch": recorded.get("branch"),
        "present": present,
        "dirty": dirty,
        "diverged": diverged,
        "lifecycle": lifecycle,
        "source_head": source_head,
        "canonical_head": canonical_head,
        "bytes_changed_after_verify": bytes_changed,
    }


def _task_from_worktree(start: Path) -> tuple[Path, dict[str, Any]]:
    root = repository_root(start)
    marker_path = git_private_path(root, "ag2c-task.json")
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
    _require_open_task(task)
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
        raise AG2CError("canonical HEAD changed during the task; run `ag2c task refresh` or start a new task")
    stale_receipt = receipt_path(canonical_manifest, str(task["id"]))
    if stale_receipt.is_file():
        stale_receipt.unlink()
    actual_paths = changed_paths(worktree, task["source"]["head"])
    if not actual_paths:
        raise AG2CError("task worktree has no changes to verify")
    manifest = load_manifest(discover_manifest(worktree), project_root=worktree)
    policy = load_policy(manifest)
    path_specs, unmanaged = _changed_specs(manifest, actual_paths)
    if unmanaged:
        _record_intervention(canonical, canonical_manifest, task, "ungoverned-change-blocked", {"paths": unmanaged})
        raise AG2CError("changed paths are outside the governed project: " + ", ".join(unmanaged))
    policy_digest = digest_file(policy.path)
    manifest_digest = digest_file(manifest.path)
    recorded_policy = str(task.get("source", {}).get("policy_digest", ""))
    recorded_manifest = str(task.get("source", {}).get("manifest_digest", ""))
    governance_changed = bool(
        (recorded_policy and recorded_policy != policy_digest)
        or (recorded_manifest and recorded_manifest != manifest_digest)
    )
    verify_all_mode = bool(task["entry"]["all"]) or governance_changed
    if governance_changed and not any(
        item.get("kind") == "governance-changed" for item in task.get("interventions", [])
    ):
        _record_intervention(
            canonical,
            canonical_manifest,
            task,
            "governance-changed",
            {"policy_digest": policy_digest, "manifest_digest": manifest_digest},
        )
    last_pass = next((item for item in reversed(task.get("verifications", [])) if item.get("passed")), None)
    current_digest = change_digest(worktree, task["source"]["head"])
    if task["state"] == "verified" and last_pass and current_digest != last_pass.get("change_digest"):
        task["state"] = "active"
        _record_intervention(
            canonical,
            canonical_manifest,
            task,
            "verified-bytes-changed",
            {"previous_digest": last_pass.get("change_digest"), "change_digest": current_digest},
        )
    build_index(manifest, policy, index_path(manifest))
    actual_slice = compile_slice(
        manifest,
        policy,
        path_specs=path_specs,
        contract_specs=list(task["entry"]["contracts"]),
        goal=str(task["goal"]),
        all_mode=verify_all_mode,
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
        all_mode=verify_all_mode,
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
        "route": actual_slice["route"],
        "route_cards": [item["id"] for item in actual_slice["cards"]],
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
    task["state"] = "verified" if passed else "active"
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
    return {
        "task_id": task["id"],
        "state": task["state"],
        "passed": passed,
        "verification": verification,
        "worktree": _worktree_snapshot(canonical, task),
    }


def finish_task(start: Path, task_id: str, *, message: str) -> dict[str, Any]:
    root = repository_root(start)
    status = activation_status(root)
    canonical = Path(status["canonical_root"])
    if root != canonical:
        raise AG2CError(f"finish AG2C tasks from the canonical worktree: {canonical}")
    if not status["managed"]:
        raise AG2CError("AG2C is not active")
    task = _load_task(canonical, task_id)
    _require_open_task(task)
    manifest, policy = _canonical_manifest(canonical)
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
        raise AG2CError("canonical branch or HEAD changed; run `ag2c task refresh` or start a new task")
    current_digest = change_digest(worktree, task["source"]["head"])
    if current_digest != task["verifications"][-1]["change_digest"]:
        raise AG2CError("task changed after verification; run `ag2c task verify` again")
    receipt = build_receipt(manifest, policy, task)
    evidence_path = write_receipt(manifest, receipt)
    commit_message = (
        message.rstrip()
        + f"\n\nAG2C-Task: {task['id']}"
        + f"\nAG2C-Evidence: {receipt['receipt_digest']}"
    )
    if status_entries(worktree):
        git(worktree, "add", "--all")
    elif head(worktree) == task["source"]["head"]:
        raise AG2CError("task worktree has no commit or changes to integrate")
    git(worktree, "commit", "--allow-empty", "-m", commit_message)
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
    validated_evidence = verify_commit_receipt(worktree, task_commit)
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
        "receipt_path": str(evidence_path),
        "receipt_digest": validated_evidence["receipt_digest"],
    }
    event = append_event(
        manifest.ledger_path,
        "task-completed",
        {"task_id": task_id, **task["result"], "intervention_count": len(task["interventions"])},
    )
    task["result"]["ledger_event_digest"] = event["event_digest"]
    _atomic_json(_task_path(canonical, task_id), task)
    try:
        git(canonical, "worktree", "remove", str(worktree))
        git(canonical, "branch", "-d", task["worktree"]["branch"])
        cleanup = "removed"
    except AG2CError as exc:
        cleanup = f"pending: {exc}"
    task["cleanup"] = cleanup
    from .govern import record_pending_from_task

    pending = record_pending_from_task(canonical, list(task["verifications"][-1].get("changed_paths") or []))
    task["governance_pending"] = pending
    _atomic_json(_task_path(canonical, task_id), task)
    return task


def list_tasks(start: Path) -> list[dict[str, Any]]:
    canonical = Path(activation_status(start)["canonical_root"])
    return [
        {
            "id": task["id"],
            "goal": task["goal"],
            "state": task["state"],
            "created_at": task.get("created_at"),
            "source": task.get("source"),
            "worktree": _worktree_snapshot(canonical, task),
        }
        for task in task_records(canonical)
    ]


def refresh_task(start: Path, task_id: str) -> dict[str, Any]:
    root = repository_root(start)
    status = activation_status(root)
    canonical = Path(status["canonical_root"])
    if root != canonical:
        raise AG2CError(f"refresh AG2C tasks from the canonical worktree: {canonical}")
    if not status["managed"]:
        raise AG2CError("AG2C is not active")
    task = _load_task(canonical, task_id)
    _require_open_task(task)
    dirty = status_entries(canonical)
    if dirty:
        raise AG2CError("canonical worktree is dirty; refusing refresh: " + ", ".join(dirty))
    worktree = Path(task["worktree"]["path"]).resolve()
    if not worktree.is_dir():
        raise AG2CError(f"task worktree is missing: {worktree}")
    if repository_root(worktree) != worktree or current_branch(worktree) != task["worktree"]["branch"]:
        raise AG2CError("task worktree identity no longer matches its AG2C record")
    manifest, policy = _canonical_manifest(canonical)
    current_head = head(canonical)
    previous_head = str(task["source"]["head"])
    if current_head == previous_head:
        return {**task, "refreshed": False, "worktree": _worktree_snapshot(canonical, task)}
    if not is_ancestor(canonical, previous_head, current_head):
        _record_intervention(
            canonical,
            manifest,
            task,
            "canonical-history-rewritten",
            {"expected": previous_head, "actual": current_head},
        )
        raise AG2CError(
            "canonical history no longer contains the task source commit; abandon this worktree or start a new task"
        )
    try:
        rebase_worktree(worktree, current_head, stash_message=f"ag2c-refresh-{task_id}")
    except AG2CError as exc:
        _record_intervention(
            canonical,
            manifest,
            task,
            "refresh-conflict",
            {"previous": previous_head, "actual": current_head, "error": str(exc)},
        )
        raise
    task["source"].setdefault("started_head", previous_head)
    task["source"].setdefault("started_branch", task["source"].get("branch"))
    task["state"] = "active"
    task["source"]["head"] = current_head
    task["source"]["branch"] = current_branch(canonical)
    task["source"]["policy_digest"] = digest_file(policy.path)
    task["source"]["manifest_digest"] = digest_file(manifest.path)
    _record_intervention(
        canonical,
        manifest,
        task,
        "source-refreshed",
        {"previous": previous_head, "source_head": current_head},
    )
    event = append_event(
        manifest.ledger_path,
        "task-refreshed",
        {"task_id": task_id, "previous_head": previous_head, "source_head": current_head},
    )
    task["refresh_ledger_event_digest"] = event["event_digest"]
    _atomic_json(_task_path(canonical, task_id), task)
    return {**task, "refreshed": True, "worktree": _worktree_snapshot(canonical, task)}


def abandon_task(start: Path, task_id: str, *, reason: str = "") -> dict[str, Any]:
    root = repository_root(start)
    status = activation_status(root)
    canonical = Path(status["canonical_root"])
    if root != canonical:
        raise AG2CError(f"abandon AG2C tasks from the canonical worktree: {canonical}")
    if not status["managed"]:
        raise AG2CError("AG2C is not active")
    task = _load_task(canonical, task_id)
    _require_open_task(task)
    reason = reason.strip() or "abandoned by operator"
    manifest, _ = _canonical_manifest(canonical)
    worktree = str(Path(task["worktree"]["path"]))
    cleanup = _remove_task_worktree(canonical, task, force=True)
    task["state"] = "abandoned"
    task["abandoned_at"] = _now()
    task["abandon"] = {
        "reason": reason,
        "source_head": task["source"]["head"],
        "worktree": worktree,
    }
    event = append_event(
        manifest.ledger_path,
        "task-abandoned",
        {"task_id": task_id, **task["abandon"]},
    )
    task["abandon"]["ledger_event_digest"] = event["event_digest"]
    task["cleanup"] = cleanup
    _atomic_json(_task_path(canonical, task_id), task)
    return {**task, "worktree": _worktree_snapshot(canonical, task)}


def task_record(start: Path, task_id: str) -> dict[str, Any]:
    canonical = Path(activation_status(start)["canonical_root"])
    return _load_task(canonical, task_id)


def task_records(start: Path) -> list[dict[str, Any]]:
    canonical = Path(activation_status(start)["canonical_root"])
    directory = load_manifest(discover_manifest(canonical)).state_dir / "tasks"
    records = [_load_task(canonical, path.stem) for path in directory.glob("*.json")] if directory.is_dir() else []
    return sorted(records, key=lambda item: str(item.get("created_at", "")), reverse=True)


def _local_evidence(canonical: Path, task: dict[str, Any]) -> dict[str, Any]:
    result = task.get("result")
    if not isinstance(result, dict) or not result.get("receipt_path") or not result.get("commit"):
        return {"status": "not-created"}
    try:
        report = verify_commit_receipt(canonical, str(result["commit"]))
    except AG2CError as exc:
        return {"status": "invalid", "error": str(exc), "path": result.get("receipt_path")}
    return {
        "status": "valid",
        "path": report["receipt_path"],
        "digest": report["receipt_digest"],
    }


def evidence(start: Path, task_id: str | None = None) -> dict[str, Any]:
    status = activation_status(start)
    canonical = Path(status["canonical_root"])
    manifest, policy = _canonical_manifest(canonical)
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
        if task.get("refresh_ledger_event_digest"):
            references.append((str(task.get("refresh_ledger_event_digest", "")), "task-refreshed"))
        if task.get("result"):
            references.append((str(task["result"].get("ledger_event_digest", "")), "task-completed"))
        if task.get("abandon"):
            references.append((str(task["abandon"].get("ledger_event_digest", "")), "task-abandoned"))
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
        if evidence_complete and task.get("abandon"):
            abandon_event = events_by_digest.get(str(task["abandon"].get("ledger_event_digest", "")))
            expected_abandon = {
                "task_id": task["id"],
                **{key: value for key, value in task["abandon"].items() if key != "ledger_event_digest"},
            }
            if abandon_event is None or abandon_event.get("payload") != expected_abandon:
                evidence_complete = False
        verified = bool(
            verifications
            and verifications[-1].get("passed")
            and _verification_evidence_valid(manifest, task, verifications[-1])
        )
        completed = task["state"] == "completed" and bool(task.get("result"))
        abandoned = task["state"] == "abandoned" and bool(task.get("abandon"))
        if completed and verified and evidence_complete:
            management_result = "successful"
        elif abandoned and evidence_complete:
            management_result = "abandoned"
        else:
            management_result = "incomplete"
        last_verification = verifications[-1] if verifications else {}
        checker_results = last_verification.get("checker_results", [])
        correction_proven = any(
            intervention.get("kind") == "ai-correction-proven"
            for intervention in task.get("interventions", [])
        )
        blocked_actions = [
            intervention.get("kind")
            for intervention in task.get("interventions", [])
            if str(intervention.get("kind", "")).endswith("-blocked")
        ]
        summaries.append(
            {
                "id": task["id"],
                "goal": task["goal"],
                "state": task["state"],
                "managed": start_valid,
                "management_result": management_result,
                "evidence_complete": evidence_complete,
                "route_state": task["route"]["state"],
                "interventions": task.get("interventions", []),
                "verification_attempts": len(verifications),
                "verifications": verifications,
                "verified": verified,
                "changed_files": list(last_verification.get("changed_paths", [])),
                "checks_run": len(checker_results),
                "checks_passed": sum(item.get("status") == "passed" for item in checker_results),
                "failed_attempts": sum(not item.get("passed", False) for item in verifications),
                "correction_proven": correction_proven,
                "blocked_actions": blocked_actions,
                "local_evidence": _local_evidence(canonical, task),
                "result": task.get("result"),
                "abandon": task.get("abandon"),
                "worktree": _worktree_snapshot(canonical, task),
                "cleanup": task.get("cleanup"),
            }
        )
    coverage = {
        "level": policy.coverage.level,
        "strategy": policy.coverage.strategy,
        "managed_by": policy.coverage.managed_by,
        "areas": list(policy.coverage.areas),
        "area_count": len([card for card in policy.cards if card.card_type == "floor"]),
        "checker_count": len(policy.checkers),
        "contract_count": len(policy.contracts),
    }
    return {
        "project": manifest.project_id,
        "managed": status["managed"],
        "ledger_valid": not ledger_errors,
        "ledger_errors": ledger_errors,
        "coverage": coverage,
        "tasks": summaries,
    }
