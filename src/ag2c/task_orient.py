"""Extracted by flatten-split."""
from __future__ import annotations
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from .acceptance import assess_product
from .checks import PROCESS_CHECK_STATUSES, run_checks
from .config import discover_manifest, load_manifest, load_policy
from .enrollment import activation_status
from .errors import AG2CError
from .storage import registered_manifest
from .gitops import change_digest, changed_paths, current_branch, git, head, is_ancestor, rebase_worktree, repository_root, status_entries
from .index import build_index, index_path
from .ledger import append_event, inspect_ledger, read_events
from .receipts import build_receipt, receipt_path, verify_commit_receipt, write_receipt
from .slicer import compile_slice
from .storage import git_private_path
from .portrait import lint_portrait, portrait_inference_section
from .util import atomic_json_write, digest_file
from .task_evidence import _matching_event, _verification_evidence_valid, _start_evidence_valid, _portrait_amendment_chain_valid
from .tasks import ORIENT_SCHEMA, TERMINAL_TASK_STATES, _atomic_json, _canonical_manifest, _load_task, _now, _record_intervention, _remove_task_worktree, _require_open_task, _sync_canonical_dirty_notification, _task_path, _worktree_snapshot, task_records
from .task_delivery import resolve_delivery

def list_tasks(start: Path) -> list[dict[str, Any]]:
    canonical = Path(activation_status(start)["canonical_root"])
    manifest = load_manifest(discover_manifest(canonical))
    canonical_head = None
    records = []
    for task in task_records(canonical, manifest=manifest):
        if task.get("state") not in TERMINAL_TASK_STATES and canonical_head is None:
            canonical_head = head(canonical)
        records.append(
            {
                "id": task["id"],
                "goal": task["goal"],
                "delivery": resolve_delivery(canonical, task),
                "state": task["state"],
                "created_at": task.get("created_at"),
                "source": task.get("source"),
                "worktree": _worktree_snapshot(canonical, task, canonical_head=canonical_head),
            }
        )
    return records

def _orient_next(
    lifecycle: str,
    *,
    has_changes: bool,
    canonical_dirty: bool,
    pending_count: int,
    task_id: str,
    worktree_path: str,
) -> dict[str, Any]:
    """Map a task lifecycle phase to the next lifecycle action. Pure function."""
    if lifecycle == "missing":
        return {
            "tool": "ag2c_task_abandon",
            "args": {"task": task_id, "reason": "<why this task is obsolete>"},
            "note": "The worktree is gone. Abandon the record, or restore the directory and orient again.",
        }
    if lifecycle == "diverged":
        return {
            "tool": "ag2c_task_refresh",
            "args": {"task": task_id},
            "note": "The canonical branch moved. Refresh rebases the worktree onto the current HEAD and invalidates passing evidence; abandon instead if the work is obsolete.",
        }
    if lifecycle == "verified-stale":
        return {
            "tool": "ag2c_task_verify",
            "args": {"cwd": worktree_path},
            "note": "Bytes changed after the last passing verification; verify the current bytes again from the worktree.",
        }
    if lifecycle == "verified-unmerged":
        note = "Run from the canonical checkout. The message names the product change and becomes the commit subject."
        if canonical_dirty:
            note += " The canonical checkout is dirty; finish refuses until it is clean."
        return {
            "tool": "ag2c_task_finish",
            "args": {"task": task_id, "message": "<what was implemented or fixed>"},
            "note": note,
        }
    if lifecycle == "completed":
        if pending_count:
            return {
                "tool": "ag2c_settle",
                "args": {"reason": "<how the pending governance items were handled>"},
                "note": f"{pending_count} governance item(s) pending after the merge.",
            }
        return {"tool": None, "args": {}, "note": "Task complete; nothing left to do."}
    if lifecycle == "abandoned":
        return {"tool": None, "args": {}, "note": "Task abandoned; start a new task if the work is still needed."}
    if not has_changes:
        return {
            "tool": None,
            "args": {},
            "note": f"No changes yet. Write code only inside the worktree, then call ag2c_task_verify: {worktree_path}",
        }
    return {
        "tool": "ag2c_task_verify",
        "args": {"cwd": worktree_path},
        "note": "Unverified changes in the worktree; verify from the actual diff.",
    }

def _orient_queue_entry(row: dict[str, Any]) -> dict[str, Any]:
    worktree = row.get("worktree") or {}
    lifecycle = str(worktree.get("lifecycle") or "")
    return {
        "task": row.get("id"),
        "goal": row.get("goal"),
        "phase": lifecycle,
        "next": _orient_next(
            lifecycle,
            has_changes=bool(worktree.get("dirty")),
            canonical_dirty=False,
            pending_count=0,
            task_id=str(row.get("id") or ""),
            worktree_path=str(worktree.get("path") or ""),
        ),
    }

def orient_task(start: Path, task_id: str | None = None) -> dict[str, Any]:
    """Orientation packet for one governed task, or the open-task queue.

    Stateless: any agent session can call this first and learn the phase, the
    lifecycle checklist, and the exact next tool call without a long-lived
    connection.
    """
    canonical = Path(activation_status(start)["canonical_root"])
    rows = list_tasks(canonical)
    open_rows = [row for row in rows if row.get("state") not in TERMINAL_TASK_STATES]
    if task_id is None:
        if not open_rows:
            return {
                "schema": ORIENT_SCHEMA,
                "queue": [],
                "message": "No open governed tasks. Start one with ag2c_task_start.",
            }
        if len(open_rows) > 1:
            return {
                "schema": ORIENT_SCHEMA,
                "message": "Several tasks are open; pick one with ag2c_task_orient(task=...).",
                "queue": [_orient_queue_entry(row) for row in open_rows],
            }
        task_id = str(open_rows[0]["id"])
    row = next((item for item in rows if item.get("id") == task_id), None)
    if row is None:
        raise AG2CError(f"unknown AG2C task: {task_id}")
    task = _load_task(canonical, task_id)
    worktree = row.get("worktree") or {}
    lifecycle = str(worktree.get("lifecycle") or "")
    worktree_path = str(worktree.get("path") or "")
    terminal = row.get("state") in TERMINAL_TASK_STATES
    changed: list[str] = []
    if not terminal and worktree.get("present") and lifecycle in {"in-progress", "verified-stale"}:
        try:
            changed = changed_paths(Path(worktree_path), str(worktree.get("source_head") or ""))
        except AG2CError:
            changed = []
    canonical_dirty: list[str] = []
    if lifecycle == "verified-unmerged":
        canonical_dirty = status_entries(canonical)
    pending_items = list((task.get("governance_pending") or {}).get("items") or [])
    verifications = list(task.get("verifications") or [])
    last_verify = verifications[-1] if verifications else None
    if terminal:
        verify_status = ("passing" if last_verify and last_verify.get("passed") else "failing") if last_verify else "not-run"
        checklist = {
            "worktree": "recycled" if not worktree.get("present") else "present",
            "construction": "merged" if row.get("state") == "completed" else "discarded",
            "verify": verify_status,
            "finish": "done" if row.get("state") == "completed" else "abandoned",
            "knowledge_sync": (f"pending: {len(pending_items)}" if pending_items else "done") if row.get("state") == "completed" else "not-applicable",
            "recycle": "done" if not worktree.get("present") else "pending",
        }
    else:
        if lifecycle == "verified-unmerged":
            verify_status = "passing"
        elif lifecycle == "verified-stale":
            verify_status = "stale-bytes"
        elif last_verify is not None and not last_verify.get("passed"):
            verify_status = "failing"
        elif last_verify is not None:
            verify_status = "passing"
        else:
            verify_status = "not-run"
        checklist = {
            "worktree": "ready" if worktree.get("present") else "missing",
            "construction": ("no changes yet" if not changed else f"{len(changed)} files changed") if lifecycle == "in-progress" else "verified bytes",
            "verify": verify_status,
            "finish": "pending",
            "knowledge_sync": "after-finish",
            "recycle": "on-finish",
        }
    blockers: list[str] = []
    if lifecycle == "missing":
        blockers.append("worktree-missing")
    if lifecycle == "diverged":
        blockers.append("canonical-moved")
    if canonical_dirty:
        blockers.append("canonical-dirty: " + ", ".join(canonical_dirty[:5]))
    return {
        "schema": ORIENT_SCHEMA,
        "task": task_id,
        "goal": row.get("goal"),
        "portrait": task.get("portrait") or "",
        "ai_additions": portrait_inference_section(str(task.get("portrait") or "")),
        "phase": lifecycle,
        "checklist": checklist,
        "next": _orient_next(
            lifecycle,
            has_changes=bool(changed),
            canonical_dirty=bool(canonical_dirty),
            pending_count=len(pending_items),
            task_id=task_id,
            worktree_path=worktree_path,
        ),
        "blockers": blockers,
        "worktree": {"path": worktree_path, "branch": worktree.get("branch")},
        "diff_summary": {"files": len(changed), "paths": changed[:20]},
        "open_tasks": len(open_rows),
    }

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
        _sync_canonical_dirty_notification(canonical, dirty, task_id=str(task["id"]))
        raise AG2CError("canonical worktree is dirty; refusing refresh: " + ", ".join(dirty))
    _sync_canonical_dirty_notification(canonical, [])
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
