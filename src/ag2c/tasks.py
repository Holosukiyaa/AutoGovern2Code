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


def _notify_gate_block(canonical: Path, kind: str, title: str, detail: str, task_id: str = "") -> None:
    """Best-effort notification; never breaks the gate itself."""
    try:
        from .notify import notify
        notify(_project_id_for(canonical), kind, title, detail, task_id=task_id)
    except Exception:
        pass


def _project_id_for(root: Path) -> str:
    try:
        manifest = load_manifest(discover_manifest(root), project_root=root)
        return manifest.project_id
    except Exception:
        return root.name


def _sync_canonical_dirty_notification(canonical: Path, dirty: list[str], task_id: str = "") -> None:
    """canonical 在任务通道外被修改的警情通知（KIND_CANONICAL_DIRTY 的生产端）。

    条件型通知：dirty 路径集为指纹——同一批路径持续脏只报一次，路径集变化
    再报；干净（空列表）时清除去重键，之后重新变脏重新报。Best-effort：
    通知是观察通道，绝不阻塞门禁本身。
    """
    try:
        from .notify import KIND_CANONICAL_DIRTY, sync_notification

        paths = sorted(str(p) for p in dirty)
        sync_notification(
            _project_id_for(canonical),
            "canonical-dirty",
            active=bool(paths),
            kind=KIND_CANONICAL_DIRTY,
            title="canonical 检出在任务通道外被修改",
            detail=", ".join(paths[:5]),
            fingerprint=hashlib.sha256("\n".join(paths).encode("utf-8")).hexdigest() if paths else "",
            task_id=task_id,
        )
    except Exception:
        pass
from .storage import registered_manifest
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
from .ledger import append_event, inspect_ledger, read_events
from .receipts import (
    build_receipt,
    receipt_path,
    verify_commit_receipt,
    write_receipt,
)
from .slicer import compile_slice
from .storage import git_private_path
from .portrait import lint_portrait, portrait_inference_section
from .util import atomic_json_write, digest_file
from .task_evidence import _matching_event, _verification_evidence_valid, _start_evidence_valid, _portrait_amendment_chain_valid

TASK_SCHEMA = "ag2c.task.v1"
OPEN_TASK_STATES = frozenset({"active", "verified"})


def _commit_subject(message: str) -> str:
    lines: list[str] = []
    for line in str(message or "").replace("\r\n", "\n").split("\n"):
        if line.strip().startswith("AG2C-"):
            continue
        lines.append(line)
    text = "\n".join(lines).strip()
    return text.split("\n", 1)[0].strip()


TERMINAL_TASK_STATES = frozenset({"completed", "abandoned"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_atomic_json = atomic_json_write


def _task_path(canonical: Path, task_id: str, *, manifest=None) -> Path:
    if manifest is None:
        manifest = load_manifest(discover_manifest(canonical))
    return manifest.state_dir / "tasks" / f"{task_id}.json"


def _load_task(canonical: Path, task_id: str, *, manifest=None) -> dict[str, Any]:
    path = _task_path(canonical, task_id, manifest=manifest)
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
    try:
        manifest = load_manifest(discover_manifest(canonical), project_root=canonical)
    except AG2CError:
        found = registered_manifest(canonical)
        if found is None:
            raise
        manifest = load_manifest(found, project_root=canonical)
    return manifest, load_policy(manifest)


BLOCKING_HOUSEHOLD_PENDING = frozenset({"opaque-household", "tighten-or-renew", "fake-child"})


def _refuse_household_debt(canonical: Path, path_specs: list[str], all_mode: bool) -> None:
    if all_mode:
        return
    from .govern import pending_updates
    from .households import census_report, households_covering_path
    from .slicer import parse_path_spec

    pending = pending_updates(canonical)
    blockers = [item for item in pending.get("items") or [] if item.get("kind") in BLOCKING_HOUSEHOLD_PENDING]
    if not blockers:
        return
    manifest, policy = _canonical_manifest(canonical)
    report = census_report(manifest, policy)
    blocker_ids = {str(item.get("path")): str(item.get("kind")) for item in blockers}
    hits: list[str] = []
    for spec in path_specs:
        try:
            target, path = parse_path_spec(spec, manifest)
        except Exception:
            continue
        for household in households_covering_path(report, target, path):
            kind = blocker_ids.get(str(household["id"]))
            if kind:
                hits.append(f"{kind}:{household['id']}")
    if hits:
        raise AG2CError("household-debt:\n- " + "\n- ".join(sorted(set(hits))))


def _ensure_worktree_location(canonical: Path, worktree: Path) -> None:
    """Refuse an in-checkout worktree unless Git ignores that path.

    A self-governed portable checkout keeps its project store under the
    Git-ignored ``data\\`` directory, so per-project task worktrees may live
    inside the checkout there. Any other in-checkout location is refused;
    use AG2C_WORKTREE_ROOT or --worktree-root to place worktrees elsewhere.
    """
    try:
        relative = worktree.relative_to(canonical)
    except ValueError:
        return
    ignored = str(git(canonical, "check-ignore", "--", relative.as_posix(), check=False)).strip()
    if ignored:
        return
    raise AG2CError(
        "AG2C task worktree must be outside the canonical project or under a Git-ignored directory: "
        + str(worktree)
    )


def _default_portrait(goal: str) -> str:
    """Minimal result-gate portrait for engine-spawned tasks; agent-facing
    surfaces (CLI/MCP) require an explicit portrait instead."""
    return f"完成态：{goal}"


def require_trunk(manifest, canonical: Path) -> str:
    """正主必须处于登记主干分支。返回当前分支名。

    finish 原本只问"任务期间分支变没变"，从不问"是不是主干"——2026-09-09
    事故：正主停在旧 feature 分支上，全天 12 个任务的合并全部落在它头上，
    主干原地不动而无人报警。一致性检查防漂移，身份检查防错位，两者都要。
    """
    branch = current_branch(canonical)
    trunk = getattr(manifest, "trunk", "")
    if not trunk:
        raise AG2CError(
            "正主未登记主干分支；请运行 ag2c govern trunk --branch <name> 登记"
            f"（当前分支：{branch or 'detached'}）"
        )
    if branch != trunk:
        raise AG2CError(
            f"正主不在登记主干上（当前 {branch or 'detached'}，登记主干 {trunk}）；"
            "请切回主干后再试"
        )
    return branch


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


def _worktree_snapshot(
    canonical: Path,
    task: dict[str, Any],
    *,
    canonical_head: str | None = None,
) -> dict[str, Any]:
    recorded = task.get("worktree") or {}
    path = Path(str(recorded.get("path", "")))
    present = bool(str(recorded.get("path", ""))) and path.is_dir()
    source_head = str(task.get("source", {}).get("head", ""))
    state = str(task.get("state", ""))
    if state in TERMINAL_TASK_STATES:
        return {
            "path": str(recorded.get("path", "")),
            "branch": recorded.get("branch"),
            "present": present,
            "dirty": False,
            "diverged": False,
            "lifecycle": "completed" if state == "completed" else "abandoned",
            "source_head": source_head,
            "canonical_head": canonical_head or "",
            "bytes_changed_after_verify": False,
        }
    if canonical_head is None:
        canonical_head = head(canonical)
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
    if not present:
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


def _is_verification_asset(relative: str) -> bool:
    """巴林条款·考卷判定：tests/ 目录下的文件，或任何位置的测试命名文件。"""
    parts = [part for part in relative.replace("\\", "/").split("/") if part]
    name = parts[-1].lower() if parts else ""
    if any(part.lower() in {"tests", "test"} for part in parts[:-1]):
        return True
    return name.startswith("test_") or name.endswith("_test.py") or name.endswith(".test.ts") or name.endswith(".test.js")


def _is_product_code(relative: str) -> bool:
    """巴林条款·产品判定：受管代码文件且不是考卷。"""
    from .households import CODE_SUFFIXES

    if _is_verification_asset(relative):
        return False
    return Path(relative).suffix.lower() in CODE_SUFFIXES


def front_back_overlap(changed_paths: list[str]) -> dict[str, list[str]]:
    """同一任务 diff 同时含产品代码与验证它的测试 = 自己改自己的考卷（巴林条款）。

    输入为仓库相对路径；返回 {"product": [...], "verification": [...]}，任一侧为空即无重叠。
    policy.json 的 checker 定义变更不在这里——它已由 governance-changed 强制全量验证覆盖。
    """
    verification = sorted({path for path in changed_paths if _is_verification_asset(path)})
    product = sorted({path for path in changed_paths if _is_product_code(path)})
    if not verification or not product:
        return {"product": [], "verification": []}
    return {"product": product, "verification": verification}


def declare_front_back(start: Path, *, reason: str) -> dict[str, Any]:
    """中途申报：本任务必须同改产品与考卷（巴林条款的申报通道）。

    申报写入任务记录（含时间戳与理由），verify 见到申报后放行但记
    intervention front-back-declared，监管提示词标注自我阅卷声明。
    """
    reason = reason.strip()
    if not reason:
        raise AG2CError("front-back declaration requires --reason")
    canonical, task = _task_from_worktree(start)
    _require_open_task(task)
    entry = task.setdefault("entry", {})
    declaration = {"declared": True, "reason": reason, "at": _now(), "via": "declare"}
    existing = entry.get("touches_verification")
    if isinstance(existing, dict) and existing.get("declared"):
        declaration["via"] = str(existing.get("via") or "declare")
    entry["touches_verification"] = declaration
    _record_intervention(canonical, _canonical_manifest(canonical)[0], task, "front-back-declared", {"reason": reason, "via": "declare"})
    return {"task": task["id"], "touches_verification": declaration}


def declare_full_scan(start: Path, *, reason: str) -> dict[str, Any]:
    """全量开关已关闭：套件只按改动文件进场，不能申报跑全家。"""
    from .suite_bind import FULL_SUITE_SWITCH_CLOSED

    raise AG2CError(FULL_SUITE_SWITCH_CLOSED)


def _committed_delta(canonical: Path, base: str, manifest) -> list[str]:
    """canonical 在 base 之后已提交的增量文件。不含未跟踪文件——rebase 不碰它们；
    账本/状态目录即使被误跟踪也视为噪声（否则并行泳道永远假相交）。"""
    raw = str(git(canonical, "diff", "--name-only", "--no-renames", base, "HEAD"))
    paths = sorted(line.strip().replace("\\", "/") for line in raw.splitlines() if line.strip())
    noise: list[str] = []
    for candidate in (manifest.ledger_path, manifest.state_dir):
        try:
            noise.append(Path(candidate).resolve().relative_to(canonical.resolve()).as_posix().rstrip("/"))
        except (ValueError, OSError):
            continue

    def keep(path: str) -> bool:
        return not any(path == prefix or path.startswith(prefix + "/") or path.startswith(prefix + ".") for prefix in noise)

    return [path for path in paths if keep(path)]


#: 治理关键路径：这些模块的代码决定 verify 本身的判罚——门禁编排（tasks）、
#: checker 执行与警告升级（checks）、监管裁决（review）、政策默认值（config，
#: regulator.strict 翻转就在这）、切片选择（slicer，决定哪些 checker 进场）、
#: 产品验收结论（acceptance）、危房判定（hazard）、选择性验证影子计划
#: （scheduler）。治理收紧必须到达执行 verify 的进程：在途任务的 worktree
#: 跑旧代码等于换锁不换门（2026-09-11 事故：strict 默认值翻转合并后，4 次
#: verify 仍被翻转前开工的 worktree 用旧代码放行——账本 17:41-18:05 UTC）。
GOVERNANCE_CODE_PATHS: tuple[str, ...] = (
    "src/ag2c/tasks.py",
    "src/ag2c/checks.py",
    "src/ag2c/review.py",
    "src/ag2c/config.py",
    "src/ag2c/slicer.py",
    "src/ag2c/acceptance.py",
    "src/ag2c/hazard.py",
    "src/ag2c/scheduler.py",
)


def _governance_code_reconcile(canonical: Path, worktree: Path, task: dict[str, Any], manifest) -> None:
    """治理代码对账（AGF 对账三件套——坐标申报/对账/降档棘轮——的第一个实例）。

    canonical 在任务开工后推进了治理关键路径、且 worktree 未包含这些更新
    （纯落后）时拒绝 verify：此时继续验证等于用旧锁验新门，通过的结论
    不可信。worktree 自己改了这些文件不算落后——那是任务内容本身；双方
    同改由既有的 canonical-head-diverged 相交检查接管（报冲突而非落后）。
    比对本身出故障（git/IO）降级为 intervention 留痕，不阻塞 verify。
    """
    source_head = str(task["source"]["head"])
    try:
        canonical_head = head(canonical)
        if canonical_head == source_head:
            return
        moved = sorted(set(_committed_delta(canonical, source_head, manifest)) & set(GOVERNANCE_CODE_PATHS))
        if not moved:
            return
        touched = set(changed_paths(worktree, source_head))
        behind = [path for path in moved if path not in touched]
    except (AG2CError, OSError) as exc:
        _record_intervention(
            canonical,
            manifest,
            task,
            "governance-code-reconcile-degraded",
            {"error": str(exc)[:200]},
        )
        return
    if not behind:
        return
    _record_intervention(
        canonical,
        manifest,
        task,
        "governance-code-behind",
        {"paths": behind, "source_head": source_head, "canonical_head": canonical_head},
    )
    raise AG2CError(
        "治理代码对账失败：canonical 已更新治理关键代码，本 worktree 跑的是旧版本，"
        "继续 verify 等于换锁不换门（治理收紧不回溯在途任务）。落后文件：\n- "
        + "\n- ".join(behind)
        + f"\n从 canonical 运行：ag2c task refresh --task {task['id']}，然后重新 verify"
        "（新进程才会加载新代码——进程内的 auto-refresh 救不了已经在跑的旧代码）。"
    )


def _auto_drill(canonical: Path) -> list[str]:
    """合并后的自动演习节律：已建队且超期的演习当场补演，返回演习纪要。

    建队制：首次演习永远手动（runs == 0 不触发）——你建立巡逻队，巡逻队
    才开始自动巡逻；这也保证测试夹具（账本无 canary 事件）不会意外触发
    真实演习。演习失败不阻断合并（木已成舟），警情留在账本与看板上。
    任何内部异常都吞掉：finish 已经成功，演习只是附带的巡逻动作。
    """
    from .patrol import patrol_report

    try:
        manifest = load_manifest(discover_manifest(canonical), project_root=canonical)
        report = patrol_report(manifest)
    except Exception:
        return []
    notes: list[str] = []
    for mode, command in (("gate", ["canary"]), ("mutation", ["canary", "--mode", "mutation"])):
        drill = report["drills"].get(mode) or {}
        if not drill.get("runs") or not drill.get("overdue"):
            continue
        label = str(drill.get("label") or mode)
        try:
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "ag2c",
                    *command,
                    "--actor",
                    "ag2c-auto-drill",
                    "--reason",
                    "自动演习节律：合并后补演超期演习",
                ],
                cwd=canonical,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=900,
            )
        except Exception as exc:
            notes.append(f"{label}自动演习未能执行：{exc}")
            continue
        if proc.returncode == 0:
            notes.append(f"{label}自动演习：已通过（缺陷被拦截）")
        else:
            notes.append(f"{label}自动演习失败：缺陷未被拦截或演习未能执行（exit {proc.returncode}），详情见账本与看板")
    return notes


ORIENT_SCHEMA = "ag2c.orient.v1"


def task_record(start: Path, task_id: str, *, manifest=None) -> dict[str, Any]:
    if manifest is None:
        canonical = Path(activation_status(start)["canonical_root"])
        manifest = load_manifest(discover_manifest(canonical))
    else:
        canonical = Path(start)
    return _load_task(canonical, task_id, manifest=manifest)


def task_records(start: Path, *, manifest=None) -> list[dict[str, Any]]:
    if manifest is None:
        canonical = Path(activation_status(start)["canonical_root"])
        manifest = load_manifest(discover_manifest(canonical))
    else:
        canonical = Path(start)
    directory = manifest.state_dir / "tasks"
    records = [_load_task(canonical, path.stem, manifest=manifest) for path in directory.glob("*.json")] if directory.is_dir() else []
    return sorted(records, key=lambda item: str(item.get("created_at", "")), reverse=True)

from .task_delivery import classify_delivery, cost_self_report, describe_delivery, resolve_delivery
from .task_orient import _orient_queue_entry
from .task_retire import _assert_retirement_diff
from .task_report import evidence, _local_evidence
from .task_finish import finish_task, _finish_hints
from .task_amend import amend_portrait
