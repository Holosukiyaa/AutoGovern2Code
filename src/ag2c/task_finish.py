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
from .tasks import _atomic_json, _auto_drill, _canonical_manifest, _changed_specs, _committed_delta, _load_task, _now, _record_intervention, _require_open_task, _sync_canonical_dirty_notification, _task_path, cost_self_report, describe_delivery, refresh_task, require_trunk, verify_task

def _proxy_flag(policy, name: str) -> bool:
    blob = getattr(policy, "proxy", None) or {}
    return isinstance(blob, dict) and blob.get(name) is True


def _proxy_auto_settle(policy) -> bool:
    return _proxy_flag(policy, "auto_settle")


def _apply_proxy_l0(canonical: Path, manifest) -> dict[str, Any]:
    from .govern import settle_pending
    from .ledger import append_event

    settled = settle_pending(canonical, actor="ag2c-proxy-l0", reason="L0 auto-settle after finish")
    append_event(manifest.ledger_path, "proxy-decision", {"rule": "settle", "actor": "ag2c-proxy-l0"})
    return settled


def _apply_proxy_census(canonical: Path, manifest, pending: dict[str, Any]) -> dict[str, Any]:
    ids = [str(item.get("path") or "") for item in pending.get("items") or [] if item.get("kind") == "census-review-required" and item.get("path")]
    if not ids:
        return pending
    from .household_commands import review_census
    from .ledger import append_event

    review_census(canonical, card_ids=ids, all_cards=False, actor="ag2c-proxy-l0", reason="L0 auto-census after finish")
    append_event(manifest.ledger_path, "proxy-decision", {"rule": "census", "actor": "ag2c-proxy-l0", "rooms": ids})
    skip = set(ids)
    return {**pending, "items": [item for item in pending.get("items") or [] if not (item.get("kind") == "census-review-required" and item.get("path") in skip)]}


_L0_WARNING_KINDS = frozenset({"file-soft-cap", "coordinate-reconciliation"})


def _apply_proxy_warning(canonical: Path, manifest) -> list[str]:
    from .checks import WARNING_ESCALATION_THRESHOLD, _load_warning_history, dismiss_warning
    from .ledger import append_event

    claimed: list[str] = []
    for entry in (_load_warning_history(manifest).get("warnings") or {}).values():
        if not isinstance(entry, dict):
            continue
        kind = str(entry.get("kind") or "")
        key = str(entry.get("key") or "")
        if kind not in _L0_WARNING_KINDS or not key or int(entry.get("count") or 0) >= WARNING_ESCALATION_THRESHOLD:
            continue
        dismiss_warning(manifest, key, actor="ag2c-proxy-l0", reason="L0 auto-claim benign warning")
        claimed.append(key)
    if claimed:
        append_event(manifest.ledger_path, "proxy-decision", {"rule": "warning", "actor": "ag2c-proxy-l0", "keys": claimed})
    return claimed


def apply_finish_proxy(canonical: Path, manifest, policy, pending: dict[str, Any]) -> dict[str, Any]:
    if _proxy_auto_settle(policy):
        remaining = _apply_proxy_l0(canonical, manifest)
        pending = {**pending, "items": list(remaining["pending"] or [])}
    if _proxy_flag(policy, "auto_census"):
        pending = _apply_proxy_census(canonical, manifest, pending)
    if _proxy_flag(policy, "auto_warning"):
        _apply_proxy_warning(canonical, manifest)
    return pending


def _finish_hints(manifest, policy, pending: dict[str, Any]) -> list[str]:
    """Actionable closing chores after a merge: settle pending items, re-review stale rooms.

    Hints only — nothing here changes settle/census behavior. Kept separate from
    finish_task so it can be unit-tested without the full task machinery.
    """
    hints: list[str] = []
    items = pending.get("items") or []
    if items:
        hints.append(
            f"{len(items)} 项治理待结算：ag2c govern settle --actor <你> --reason <结算说明>"
        )
    try:
        from .households import census_report

        stale_rooms = [
            item["id"]
            for item in census_report(manifest, policy).get("households", [])
            if item.get("freshness") != "current"
        ]
    except Exception:
        stale_rooms = []
    if stale_rooms:
        listed = "、".join(stale_rooms[:5])
        suffix = " 等" if len(stale_rooms) > 5 else ""
        hints.append(
            f"{len(stale_rooms)} 个房间普查陈旧（{listed}{suffix}）：复核后运行 ag2c govern census --record --all --actor <你> --reason <复核说明>"
        )
    return hints

def finish_task(
    start: Path,
    task_id: str,
    *,
    message: str,
    proof: str = "",
    sessions: int | None = None,
    estimated_tokens: dict[str, Any] | None = None,
    _auto_recovered: bool = False,
) -> dict[str, Any]:
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
    require_trunk(manifest, canonical)
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
        _sync_canonical_dirty_notification(canonical, dirty, task_id=str(task["id"]))
        raise AG2CError("canonical worktree is dirty; refusing merge")
    _sync_canonical_dirty_notification(canonical, [])
    if head(canonical) != task["source"]["head"] or current_branch(canonical) != task["source"]["branch"]:
        # 并行税自愈：canonical 增量与已验证的任务路径不相交时，自动 refresh +
        # 内联重验 + 重入 finish（全部门禁重跑，证据重新绑定到新 HEAD）。
        # 分支变更或路径相交维持硬报错。
        if (
            not _auto_recovered
            and current_branch(canonical) == task["source"]["branch"]
            and head(canonical) != task["source"]["head"]
        ):
            verified_paths = set(task["verifications"][-1].get("changed_paths", []))
            delta = set(_committed_delta(canonical, str(task["source"]["head"]), manifest))
            if delta and not (delta & verified_paths):
                refresh_task(canonical, task_id)
                verify_task(worktree)
                return finish_task(
                    start,
                    task_id,
                    message=message,
                    proof=proof,
                    sessions=sessions,
                    estimated_tokens=estimated_tokens,
                    _auto_recovered=True,
                )
        raise AG2CError("canonical branch or HEAD changed; run `ag2c task refresh` or start a new task")
    current_digest = change_digest(worktree, task["source"]["head"])
    if current_digest != task["verifications"][-1]["change_digest"]:
        raise AG2CError("task changed after verification; run `ag2c task verify` again")
    from .trust_base import require_trust_base_approval

    require_trust_base_approval(task, list(task["verifications"][-1].get("changed_paths") or []))
    if policy.household_required:
        from .households import enforce_households

        work_manifest = load_manifest(discover_manifest(worktree), project_root=worktree)
        actual_specs, _unmanaged = _changed_specs(work_manifest, task["verifications"][-1]["changed_paths"])
        entries = [{"target": spec.partition(":")[0], "path": spec.partition(":")[2]} for spec in actual_specs]
        passing_checks = {item["id"] for item in task["verifications"][-1]["checker_results"] if item["status"] == "passed"}
        enforce_households(work_manifest, policy, {"entries": {"paths": entries}}, passing_checks)
    delivery = describe_delivery(goal=str(task.get("goal") or ""), outcome=message)
    if not delivery["outcome"]:
        raise AG2CError("AG2C requires a finish message that says what was implemented or fixed")
    task["delivery"] = delivery
    task["proof"] = proof.strip()
    self_report = cost_self_report(sessions=sessions, estimated_tokens=estimated_tokens)
    if self_report is not None:
        task["cost_self_report"] = self_report
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
    completed_payload: dict[str, Any] = {
        "task_id": task_id,
        **task["result"],
        "proof": task["proof"],
        "intervention_count": len(task["interventions"]),
        "kind": delivery["kind"],
    }
    if self_report is not None:
        completed_payload["cost_self_report"] = self_report
    event = append_event(
        manifest.ledger_path,
        "task-completed",
        completed_payload,
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
    pending = apply_finish_proxy(canonical, manifest, policy, pending)
    task["governance_pending"] = pending
    task["hints"] = _finish_hints(manifest, policy, pending)
    drill_notes = _auto_drill(canonical)
    if drill_notes:
        task["auto_drills"] = drill_notes
        task["hints"] = task["hints"] + drill_notes
    from .journal import mark_version

    journal = mark_version(canonical, task=task)
    task["journal_version"] = journal["version"]
    _atomic_json(_task_path(canonical, task_id), task)
    return task
