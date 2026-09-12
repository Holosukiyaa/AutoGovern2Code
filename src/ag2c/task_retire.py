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
from .tasks import OPEN_TASK_STATES, _canonical_manifest, list_tasks

def _assert_retirement_diff(canonical: Path, worktree: Path, task: dict[str, Any], changed_paths: list[str]) -> None:
    # 删除的口径 = 内容真正从仓库消失。保留 git 改名判定（不加 --no-renames）：
    # git mv / rehome 的"删源+加目"是移动而非删除，内容仍在树内，由 rehome 自己的
    # 治理环路（scope 更新→import 改写→census→verify）负责，本门不拦。代价是
    # 字节级相同的 删A+加B 会被判成改名而绕过 touches-active——git 层面这与移动
    # 不可区分，接受 git 的判定并在此明记。
    deleted = [
        line.strip().replace("\\", "/")
        for line in str(git(worktree, "diff", "--name-only", "--diff-filter=D", task["source"]["head"])).splitlines()
        if line.strip()
    ]
    if not deleted:
        return
    from .households import census_report, households_covering_path, scan_references
    from .household_commands import load_retirement_confirms

    manifest, policy = _canonical_manifest(canonical)
    report = census_report(manifest, policy)
    confirms = load_retirement_confirms(manifest)
    open_ids = [
        str(item.get("id"))
        for item in list_tasks(canonical)
        if item.get("state") in OPEN_TASK_STATES and item.get("id") != task.get("id")
    ]
    leftover_ids = {
        str(item["id"])
        for item in report.get("households") or []
        if item.get("identity") == "leftover" or str((item.get("jurisdiction") or {}).get("status") or "") in {"legacy", "retired"}
    }

    def _is_leftover(household: dict[str, Any]) -> bool:
        return str(household["id"]) in leftover_ids

    def _is_file_grain(household: dict[str, Any]) -> bool:
        return str((household.get("jurisdiction") or {}).get("grain") or "") == "file"

    def _check_retired_household(household: dict[str, Any], path: str) -> None:
        declaration = household.get("jurisdiction") or {}
        status = str(declaration.get("status") or "")
        if status == "legacy" and not household.get("replaced_by"):
            raise AG2CError(f"cannot-delete-without-replacement:{household['id']}")
        if declaration.get("decider") == "confirm" and household["id"] not in confirms:
            raise AG2CError(f"retirement-confirm-required:{household['id']}")

    for path in deleted:
        owners = households_covering_path(report, "app", path)
        if not owners:
            raise AG2CError(f"cannot-delete-unowned:{path}")
        # 文件粒度户口（t59）比房间户口更具体，具体者优先：文件户口精确覆盖
        # 该路径时以它为准，所在房间仍 active 不阻挡——删单个文件不再要求先拆掉
        # 整个房间。叠加口径：同一路径上只要有一张 current 文件户口就仍挡（活着
        # 的具体声明优先于退役的）；全部退役才按退役链约束放行。
        file_owners = [item for item in owners if _is_file_grain(item)]
        if file_owners:
            active_file = [item for item in file_owners if not _is_leftover(item)]
            if active_file:
                raise AG2CError(f"cannot-delete-active-household:{active_file[0]['id']}:{path}")
            for household in file_owners:
                _check_retired_household(household, path)
            if open_ids:
                raise AG2CError("cannot-delete-while-tasks-open:" + ",".join(open_ids))
            continue
        for household in owners:
            declaration = household.get("jurisdiction") or {}
            identity = str(household.get("identity") or "")
            status = str(declaration.get("status") or "")
            if status == "current" and identity not in {"leftover"}:
                raise AG2CError(f"cannot-delete-active-household:{household['id']}:{path}")
            _check_retired_household(household, path)
        if open_ids:
            raise AG2CError("cannot-delete-while-tasks-open:" + ",".join(open_ids))
    for path in changed_paths:
        owners = households_covering_path(report, "app", path)
        if owners and not any(_is_leftover(item) for item in owners):
            raise AG2CError(f"retirement-diff-touches-active:{path}")
    hits = scan_references(worktree, deleted, set(deleted))
    if hits:
        raise AG2CError("retirement-references:\n- " + "\n- ".join(hits[:20]))
