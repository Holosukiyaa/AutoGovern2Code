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
from .acceptance import assess_product, coverage_view
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
from .tasks import TERMINAL_TASK_STATES, _canonical_manifest, _worktree_snapshot, task_record, task_records
from .task_delivery import resolve_delivery

def _local_evidence(canonical: Path, task: dict[str, Any], *, verify: bool = True) -> dict[str, Any]:
    result = task.get("result")
    if not isinstance(result, dict) or not result.get("receipt_path") or not result.get("commit"):
        return {"status": "not-created"}
    receipt = Path(str(result["receipt_path"]))
    if not verify:
        if receipt.is_file():
            return {"status": "recorded", "path": str(receipt)}
        return {"status": "missing", "path": str(receipt)}
    try:
        report = verify_commit_receipt(canonical, str(result["commit"]))
    except AG2CError as exc:
        return {"status": "invalid", "error": str(exc), "path": result.get("receipt_path")}
    return {
        "status": "valid",
        "path": report["receipt_path"],
        "digest": report["receipt_digest"],
    }

def evidence(
    start: Path,
    task_id: str | None = None,
    *,
    verify_local: bool = True,
    activation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    status = activation if activation is not None else activation_status(start)
    canonical = Path(status["canonical_root"])
    manifest, policy = _canonical_manifest(canonical)
    knowledge_rows: list[dict[str, Any]] = []
    census = None
    if verify_local:
        from .knowledge import knowledge_status

        knowledge_rows = knowledge_status(manifest, policy)
        try:
            from .households import census_report

            census = census_report(manifest, policy)
        except Exception:
            census = None
    ledger_errors, events = inspect_ledger(manifest.ledger_path)
    if ledger_errors:
        events = []
    events_by_digest = {str(event["event_digest"]): event for event in events}
    records = (
        [task_record(canonical, task_id, manifest=manifest)]
        if task_id
        else task_records(canonical, manifest=manifest)
    )
    summaries = []
    canonical_head = None
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
        start_valid = not ledger_errors and _start_evidence_valid(
            manifest, task, events_by_digest=events_by_digest
        )
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
        verification_valid = [
            _verification_evidence_valid(manifest, task, verification, events_by_digest=events_by_digest)
            for verification in verifications
        ]
        if evidence_complete and any(not item for item in verification_valid):
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
        last_verification_valid = bool(verification_valid and verification_valid[-1])
        verified = bool(verifications and verifications[-1].get("passed") and last_verification_valid)
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
        product = assess_product(policy, knowledge=knowledge_rows, verification=last_verification or None, census=census)
        correction_proven = any(
            intervention.get("kind") == "ai-correction-proven"
            for intervention in task.get("interventions", [])
        )
        blocked_actions = [
            intervention.get("kind")
            for intervention in task.get("interventions", [])
            if str(intervention.get("kind", "")).endswith("-blocked")
        ]
        if task.get("state") not in TERMINAL_TASK_STATES and canonical_head is None:
            canonical_head = head(canonical)
        summaries.append(
            {
                "id": task["id"],
                "goal": task["goal"],
                "delivery": resolve_delivery(canonical, task),
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
                "product": product,
                "local_evidence": _local_evidence(canonical, task, verify=verify_local),
                "result": task.get("result"),
                "abandon": task.get("abandon"),
                "worktree": _worktree_snapshot(canonical, task, canonical_head=canonical_head),
                "cleanup": task.get("cleanup"),
            }
        )
    coverage = coverage_view(policy, project_root=manifest.project_root)
    return {
        "project": manifest.project_id,
        "managed": status["managed"],
        "ledger_valid": not ledger_errors,
        "ledger_errors": ledger_errors,
        "coverage": coverage,
        "product": assess_product(
            policy,
            knowledge=knowledge_rows,
            verification=(summaries[0].get("verifications") or [None])[-1] if summaries else None,
            census=census,
        ),
        "tasks": summaries,
    }
