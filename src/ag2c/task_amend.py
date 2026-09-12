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
from .tasks import _canonical_manifest, _record_intervention, _require_open_task, _task_from_worktree

def amend_portrait(start: Path, *, portrait: str, actor: str, reason: str) -> dict[str, Any]:
    """画像修订：任务中途按市长指名的纠偏更换已锁画像。

    画像在 start 时锁定，但锁定口径可能本身就是错的——2026-09-10 D→D2
    事故：画像写着 <=60s 而实际预算是 <=90s，没有修订通道只能废弃重开，
    全部上下文重来。修订走与申报相同的证据链：lint 新画像、替换记录、
    记 intervention portrait-amended（actor/reason/新旧 digest 落账本）。
    verify 时监管看到修订史，裁决每次修订是市长指名纠偏还是自利漂移。
    """
    portrait = portrait.strip()
    if not portrait:
        raise AG2CError("portrait amendment requires --portrait")
    actor = actor.strip()
    if not actor:
        raise AG2CError("portrait amendment requires --actor（画像修订是市长级动作，必须署名）")
    reason = reason.strip()
    if not reason:
        raise AG2CError("portrait amendment requires --reason（市长指名的纠偏内容，进证据链）")
    violations = lint_portrait(portrait)
    if violations:
        raise AG2CError("portrait lint failed:\n- " + "\n- ".join(violations))
    canonical, task = _task_from_worktree(start)
    _require_open_task(task)
    old = str(task.get("portrait") or "")
    if portrait == old.strip():
        raise AG2CError("portrait is unchanged; nothing to amend")
    old_digest = hashlib.sha256(old.encode("utf-8")).hexdigest()
    new_digest = hashlib.sha256(portrait.encode("utf-8")).hexdigest()
    task["portrait"] = portrait
    _record_intervention(
        canonical,
        _canonical_manifest(canonical)[0],
        task,
        "portrait-amended",
        {"actor": actor, "reason": reason, "old_digest": old_digest, "new_digest": new_digest},
    )
    return {
        "task": task["id"],
        "portrait_amended": {"actor": actor, "reason": reason, "old_digest": old_digest, "new_digest": new_digest},
    }
