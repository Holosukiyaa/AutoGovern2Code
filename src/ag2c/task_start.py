"""Extracted by flatten-split."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from .enrollment import activation_status
from .errors import AG2CError
from .gitops import current_branch, git, head, repository_root, status_entries
from .index import build_index, index_path
from .ledger import append_event
from .portrait import lint_portrait, portrait_inference_section
from .slicer import compile_slice
from .storage import git_private_path
from .tasks import (
    TASK_SCHEMA,
    _atomic_json,
    _canonical_manifest,
    _default_portrait,
    _ensure_worktree_location,
    _notify_gate_block,
    _now,
    _refuse_household_debt,
    _task_id,
    _task_path,
    require_trunk,
)
from .util import digest_file


def start_task(
    start: Path,
    *,
    goal: str,
    path_specs: list[str],
    contract_specs: list[str],
    all_mode: bool = False,
    task_id: str | None = None,
    worktree_root: Path | None = None,
    portrait: str = "",
    touches_verification: bool = False,
    coordinates: dict[str, Any] | None = None,
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
    portrait = portrait.strip()
    if portrait:
        violations = lint_portrait(portrait)
        if violations:
            raise AG2CError("portrait lint failed:\n- " + "\n- ".join(violations))
    dirty = status_entries(canonical)
    if dirty:
        _notify_gate_block(canonical, "gate-block", "canonical 检出被修改", ", ".join(dirty[:5]))
        raise AG2CError("canonical worktree is dirty; AG2C will not start: " + ", ".join(dirty))
    if all_mode:
        from .suite_bind import FULL_SUITE_SWITCH_CLOSED

        raise AG2CError(FULL_SUITE_SWITCH_CLOSED)
    if not path_specs and not contract_specs:
        raise AG2CError("AG2C requires exact paths/contracts before work begins")
    try:
        _refuse_household_debt(canonical, path_specs, all_mode)
    except AG2CError as exc:
        _notify_gate_block(canonical, "gate-block", "房间债务拦截", str(exc)[:200])
        raise
    manifest, policy = _canonical_manifest(canonical)
    require_trunk(manifest, canonical)
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
    # AGF 坐标申报（对账三件套第一件）：申报校验 + 卡片推导 + 三桶来源标注，
    # 随任务记录与 task-started 账本事件落账——本任务只申报记录，对账执法
    # 是后续任务。非法枚举值在 worktree 创建之前拒绝，不留半成品。
    from .coordinates import constraint_warnings, resolve_coordinates
    from .households import coerce_jurisdiction

    jurisdictions = []
    for item in entry_slice.get("cards", []):
        try:
            card = policy.card(str(item.get("id")))
        except StopIteration:
            continue
        jurisdiction = coerce_jurisdiction(card.jurisdiction)
        if jurisdiction:
            jurisdictions.append(jurisdiction)
    resolved_coordinates = resolve_coordinates(coordinates, jurisdictions)
    configured_root = os.environ.get("AG2C_WORKTREE_ROOT")
    base = worktree_root or (Path(configured_root) if configured_root else manifest.path.parent / "worktrees")
    worktree = (base.resolve() / task_id).resolve()
    _ensure_worktree_location(canonical, worktree)
    if worktree.exists():
        raise AG2CError(f"task worktree already exists: {worktree}")
    branch = f"ag2c/{task_id}"
    worktree.parent.mkdir(parents=True, exist_ok=True)
    git(canonical, "worktree", "add", "-b", branch, str(worktree), source_head)
    if not portrait:
        portrait = _default_portrait(goal)
    task: dict[str, Any] = {
        "schema": TASK_SCHEMA,
        "id": task_id,
        "state": "active",
        "goal": goal,
        "portrait": portrait,
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
        "entry": {
            "paths": path_specs,
            "contracts": contract_specs,
            "all": all_mode,
            **(
                {"touches_verification": {"declared": True, "reason": "declared at task start", "at": _now(), "via": "start"}}
                if touches_verification
                else {}
            ),
        },
        "route": {
            "state": entry_slice["route"]["state"],
            "slice_digest": entry_slice["slice_digest"],
            "fallback_reasons": entry_slice["route"]["fallback_reasons"],
            "checker_ids": [item["id"] for item in entry_slice["check_plan"]],
        },
        "coordinates": resolved_coordinates,
        "interventions": [],
        "verifications": [],
    }
    _atomic_json(record_path, task)
    # 维度间约束机查（警告不拦）：quality=human 而 decider 不到人时记
    # warning-history。kind 不在 ESCALATABLE_KINDS，永不硬化成门。
    coordinate_warnings = constraint_warnings(task_id, resolved_coordinates["effective"])
    if coordinate_warnings:
        from .checks import _record_warnings_and_find_escalated

        _record_warnings_and_find_escalated(manifest, coordinate_warnings, count_key=task_id)
    marker = git_private_path(worktree, "ag2c-task.json")
    _atomic_json(marker, {"schema": TASK_SCHEMA, "task_id": task_id, "canonical_root": str(canonical)})
    event = append_event(
        manifest.ledger_path,
        "task-started",
        {
            "task_id": task_id,
            "goal": task["goal"],
            "portrait": task["portrait"],
            "source_head": source_head,
            "source_branch": source_branch,
            "worktree": str(worktree),
            "worktree_branch": branch,
            "slice_digest": entry_slice["slice_digest"],
            "route_state": entry_slice["route"]["state"],
            "coordinates": task["coordinates"],
        },
    )
    task["start_ledger_event_digest"] = event["event_digest"]
    _atomic_json(record_path, task)
    from .govern import retrieve_guidance

    return {
        **task,
        # 加料清单浮现：用户没说、AI 自行添加的部分，start 当场给人看
        "ai_additions": portrait_inference_section(task["portrait"]),
        "guidance": retrieve_guidance(canonical, path_specs=path_specs, contract_specs=contract_specs, goal=goal, all_mode=all_mode),
    }
