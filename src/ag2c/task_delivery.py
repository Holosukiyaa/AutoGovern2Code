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
from .tasks import _commit_subject

def classify_delivery(text: str) -> str:
    value = str(text or "").lower()
    if any(token in value for token in ("fix", "bug", "hotfix", "修复", "问题", "缺陷", "故障")):
        return "fix"
    if any(token in value for token in ("feat", "feature", "implement", "实现", "功能", "新增")):
        return "feature"
    if any(token in value for token in ("chore", "docs", "refactor", "test:", "对齐", "升级", "文档")):
        return "chore"
    return "change"

def cost_self_report(
    *,
    sessions: int | None = None,
    estimated_tokens: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """finish 可选自报。标 INFERRED；非法值拒绝。不传则不落字段。"""
    if sessions is None and not estimated_tokens:
        return None
    report: dict[str, Any] = {"source": "INFERRED"}
    if sessions is not None:
        if type(sessions) is not int or sessions < 0:
            raise AG2CError("sessions must be a non-negative integer")
        report["sessions"] = sessions
    if estimated_tokens:
        if not isinstance(estimated_tokens, dict):
            raise AG2CError("estimated_tokens must be an object {model, input, output}")
        model = str(estimated_tokens.get("model") or "").strip()
        raw_in = estimated_tokens.get("input")
        raw_out = estimated_tokens.get("output")
        if not model or type(raw_in) is not int or type(raw_out) is not int or raw_in < 0 or raw_out < 0:
            raise AG2CError("estimated_tokens must be {model, input, output} with non-negative ints")
        report["estimated_tokens"] = {"model": model, "input": raw_in, "output": raw_out}
    return report

def describe_delivery(*, goal: str, outcome: str) -> dict[str, str]:
    request = str(goal or "").strip()
    delivered = _commit_subject(outcome) or request
    return {
        "request": request,
        "outcome": delivered,
        "kind": classify_delivery(f"{delivered} {request}"),
    }

def resolve_delivery(canonical: Path, task: dict[str, Any]) -> dict[str, str]:
    recorded = task.get("delivery")
    if isinstance(recorded, dict) and str(recorded.get("outcome") or "").strip():
        outcome = str(recorded.get("outcome") or "").strip()
        request = str(recorded.get("request") or task.get("goal") or "").strip()
        return {
            "request": request,
            "outcome": outcome,
            "kind": str(recorded.get("kind") or classify_delivery(f"{outcome} {request}")),
        }
    outcome = ""
    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    commit = str(result.get("commit") or "")
    if commit:
        try:
            outcome = _commit_subject(str(git(canonical, "show", "-s", "--format=%B", commit)))
        except AG2CError:
            outcome = ""
    return describe_delivery(goal=str(task.get("goal") or ""), outcome=outcome)
