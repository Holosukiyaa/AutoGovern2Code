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
from .suite_bind import disk_engine_src
from .portrait import lint_portrait, portrait_inference_section
from .util import atomic_json_write, digest_file, hidden_process_kwargs
from .task_evidence import _matching_event, _verification_evidence_valid, _start_evidence_valid, _portrait_amendment_chain_valid
from .tasks import _assert_retirement_diff, _atomic_json, _canonical_manifest, _changed_specs, _committed_delta, _governance_code_reconcile, _notify_gate_block, _now, _record_intervention, _require_open_task, _sync_canonical_dirty_notification, _task_from_worktree, _task_path, _worktree_snapshot, front_back_overlap
from .task_orient import refresh_task

VERIFY_REEXEC_ENV = "AG2C_VERIFY_REEXEC"


def _console_python() -> str:
    exe = Path(sys.executable)
    if exe.stem.lower() == "pythonw":
        sibling = exe.with_name("python.exe" if exe.suffix.lower() == ".exe" else "python")
        if sibling.is_file():
            return str(sibling)
    return str(exe)


def _parse_verify_json(stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    decoder = json.JSONDecoder()
    payload: dict[str, Any] | None = None
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            obj, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "passed" in obj:
            payload = obj
    if payload is None:
        raise AG2CError("verify child produced no JSON")
    return payload


def _reexec_verify(start: Path) -> dict[str, Any]:
    worktree = repository_root(start)
    canonical, _task = _task_from_worktree(worktree)
    src = disk_engine_src(worktree, canonical)
    env = os.environ.copy()
    env[VERIFY_REEXEC_ENV] = "1"
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(src) if not existing else str(src) + os.pathsep + existing
    completed = subprocess.run(
        [_console_python(), "-B", "-m", "ag2c", "task", "verify"],
        cwd=str(worktree),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        **hidden_process_kwargs(),
    )
    stderr = (completed.stderr or "").strip()
    if completed.returncode not in (0, 1):
        msg = stderr or (completed.stdout or "").strip() or "verify child failed"
        if msg.startswith("AG2C error:"):
            msg = msg[len("AG2C error:") :].strip()
        raise AG2CError(msg)
    return _parse_verify_json(completed.stdout or "")


def verify_task(start: Path, *, _auto_refreshed: bool = False) -> dict[str, Any]:
    if os.environ.get(VERIFY_REEXEC_ENV) != "1":
        return _reexec_verify(start)
    worktree = repository_root(start)
    canonical, task = _task_from_worktree(worktree)
    _require_open_task(task)
    canonical_manifest, _ = _canonical_manifest(canonical)
    formal_dirty = status_entries(canonical)
    if formal_dirty:
        _record_intervention(canonical, canonical_manifest, task, "canonical-write-blocked", {"paths": formal_dirty})
        _sync_canonical_dirty_notification(canonical, formal_dirty, task_id=str(task["id"]))
        raise AG2CError("canonical worktree changed during the task; refusing verification")
    _sync_canonical_dirty_notification(canonical, [])
    # 治理代码对账必须先于 HEAD 分叉自愈：auto-refresh 在同一进程内重基，
    # 磁盘字节是新的、内存里跑的仍是旧治理代码——这个洞只能靠拒绝+手动
    # refresh+新进程重验来堵。
    _governance_code_reconcile(canonical, worktree, task, canonical_manifest)
    actual_paths = changed_paths(worktree, task["source"]["head"])
    if not actual_paths:
        raise AG2CError("task worktree has no changes to verify")
    if head(canonical) != task["source"]["head"]:
        # 并行税自愈：canonical 增量与任务改动路径不相交时，自动 refresh 后继续，
        # 不再要求 agent 手动跑 refresh + 重普查 + 重 verify 的三路命令循环。
        # 相交（或增量为空但 HEAD 变了，如空提交）维持硬报错——路径级重叠需要人工判断。
        delta = _committed_delta(canonical, str(task["source"]["head"]), canonical_manifest)
        overlap = sorted(set(delta) & set(actual_paths))
        if not _auto_refreshed and delta and not overlap:
            refresh_task(canonical, str(task["id"]))
            return verify_task(start, _auto_refreshed=True)
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
    manifest = load_manifest(discover_manifest(worktree), project_root=worktree)
    policy = load_policy(manifest)
    path_specs, unmanaged = _changed_specs(manifest, actual_paths)
    if unmanaged:
        _record_intervention(canonical, canonical_manifest, task, "ungoverned-change-blocked", {"paths": unmanaged})
        raise AG2CError("changed paths are outside the governed project: " + ", ".join(unmanaged))
    overlap = front_back_overlap(actual_paths)
    if overlap["product"]:
        declaration = task.get("entry", {}).get("touches_verification")
        declared = isinstance(declaration, dict) and declaration.get("declared")
        if declared:
            if not any(item.get("kind") == "front-back-declared" for item in task.get("interventions", [])):
                _record_intervention(
                    canonical,
                    canonical_manifest,
                    task,
                    "front-back-declared",
                    {"reason": str(declaration.get("reason", "")), "via": str(declaration.get("via", "start"))},
                )
        else:
            _record_intervention(canonical, canonical_manifest, task, "front-back-violation", overlap)
            raise AG2CError(
                "front-back violation (巴林条款): this task changes product code AND the tests that verify it:\n- product: "
                + ", ".join(overlap["product"][:5])
                + "\n- verification: "
                + ", ".join(overlap["verification"][:5])
                + "\nSplit the task (product vs tests), or declare with `ag2c task declare --reason ...` and accept elevated review."
            )
    from .trust_base import require_trust_base_declaration

    require_trust_base_declaration(task, actual_paths)
    _assert_retirement_diff(canonical, worktree, task, actual_paths)
    policy_digest = digest_file(policy.path)
    manifest_digest = digest_file(manifest.path)
    recorded_policy = str(task.get("source", {}).get("policy_digest", ""))
    recorded_manifest = str(task.get("source", {}).get("manifest_digest", ""))
    governance_changed = bool(
        (recorded_policy and recorded_policy != policy_digest)
        or (recorded_manifest and recorded_manifest != manifest_digest)
    )
    if bool(task["entry"]["all"]):
        from .suite_bind import FULL_SUITE_SWITCH_CLOSED

        raise AG2CError(FULL_SUITE_SWITCH_CLOSED)
    verify_all_mode = False
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
    # 申报 vs 推导对账（对账三件套第二件 + 降档棘轮第三件）：declared 比
    # 工作集推导宽松时出警告；key 按维度稳定，count_key=task_id 跨任务计数，
    # 第 3 次同维宽松硬化。约束警告仍不进 ESCALATABLE_KINDS。
    coordinate_reconciliation: dict[str, Any] = {"warnings": []}
    try:
        declared_coordinates = dict((task.get("coordinates") or {}).get("declared") or {})
        if declared_coordinates:
            from .coordinates import derive_from_cards, reconciliation_warnings
            from .households import coerce_jurisdiction

            verify_jurisdictions = []
            for item in actual_slice.get("cards", []):
                try:
                    card = policy.card(str(item.get("id")))
                except StopIteration:
                    continue
                jurisdiction = coerce_jurisdiction(card.jurisdiction)
                if jurisdiction:
                    verify_jurisdictions.append(jurisdiction)
            derived_coordinates = derive_from_cards(verify_jurisdictions)
            recon_warnings = reconciliation_warnings(str(task["id"]), declared_coordinates, derived_coordinates)
            coordinate_reconciliation = {
                "declared": declared_coordinates,
                "derived": derived_coordinates,
                "warnings": recon_warnings,
            }
            if recon_warnings:
                from .checks import _record_warnings_and_find_escalated

                _record_warnings_and_find_escalated(canonical_manifest, recon_warnings, count_key=str(task["id"]))
    except Exception as exc:
        coordinate_reconciliation = {"error": str(exc), "warnings": []}
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
    # 调度器 Phase 1 影子模式：算出「本会跳过什么」但不真跳，plan 落 verify
    # 记录与账本事件供观察。可观测性不能成为新故障源——任何异常降级留痕。
    try:
        from .scheduler import shadow_plan

        shadow = shadow_plan(
            planned_checker_ids=[str(item["id"]) for item in report["results"]],
            all_checker_ids=[str(checker.checker_id) for checker in policy.checkers],
            change_digest=after_check_digest,
            events=read_events(canonical_manifest.ledger_path),
        )
    except Exception as exc:
        shadow = {"schema": "ag2c.shadow-plan.v1", "mode": "shadow", "error": str(exc)}
    if shadow.get("would_skip") is not None and not shadow.get("error"):
        print(
            f"影子计划：本会跳过 {len(shadow['would_skip'])}/{len(shadow.get('entries', []))} 个 checker（缓存命中），本次仍全跑",
            file=sys.stderr,
        )
    timed = [item for item in report["results"] if isinstance(item.get("duration_ms"), (int, float)) and item.get("duration_ms")]
    if timed:
        slowest = sorted(timed, key=lambda item: -item["duration_ms"])[:3]
        total_ms = sum(item["duration_ms"] for item in timed)
        summary = "、".join(f"{item['id']} {item['duration_ms'] / 1000:.1f}s" for item in slowest)
        print(f"checker 耗时：总计 {total_ms / 1000:.1f}s（串行口径），最慢 {summary}", file=sys.stderr)
    passed = (
        bool(report["results"])
        and all(item["status"] in PROCESS_CHECK_STATUSES for item in report["results"])
        and any(item["status"] == "passed" for item in report["results"])
        and not checker_mutated_change
    )
    regulator_result: dict[str, Any] | None = None
    if passed:
        from .review import run_agent_review

        regulator_result = run_agent_review(worktree, task, policy, report)
        if regulator_result["outcome"] == "rejected":
            passed = False
        elif (
            regulator_result["outcome"] == "unavailable"
            and policy.regulator is not None
            and policy.regulator.strict
        ):
            _record_intervention(
                canonical,
                canonical_manifest,
                task,
                "regulator-unavailable-strict",
                {"reason": str(regulator_result.get("reason", ""))},
            )
            raise AG2CError(
                "regulator unavailable and policy regulator.strict=true; refusing verification: "
                + str(regulator_result.get("reason", ""))
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
        # 信息性字段，独立于 checker_results：旧版 finish 的逐项比对只看 checker_results，
        # 把 duration_ms 放进那些 dict 会让旧代码判定证据不一致（版本偏斜）。
        "checker_durations": {
            item["id"]: item["duration_ms"]
            for item in report["results"]
            if isinstance(item.get("duration_ms"), (int, float))
        },
        "acceptance": report["acceptance"],
        "check_ledger_event_digest": report["ledger_event_digest"],
        "regulator": regulator_result,
        # 调度器 Phase 1：影子计划是信息性字段（同 checker_durations 的口径），
        # 不参与证据绑定的固定键比对，旧版 finish 读到也能容忍。
        "shadow_plan": shadow,
        # 坐标对账（三件套第二件）：同 shadow_plan 的信息性字段口径——可机验
        # 但不参与证据绑定比对；警告级产出，永不拦截。
        "coordinate_reconciliation": coordinate_reconciliation,
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
        failed = [item["id"] for item in report["results"] if item["status"] != "passed"]
        _notify_gate_block(
            canonical, "verify-fail",
            f"验证未通过（第 {verification['attempt']} 次）",
            "失败检查: " + ", ".join(failed[:5]),
            task_id=str(task["id"]),
        )
    return {
        "task_id": task["id"],
        "state": task["state"],
        "passed": passed,
        "verification": verification,
        "worktree": _worktree_snapshot(canonical, task),
    }
