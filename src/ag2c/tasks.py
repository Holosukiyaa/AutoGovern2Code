from __future__ import annotations

import json
import os
import re
import secrets
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
from .util import digest_file

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


def classify_delivery(text: str) -> str:
    value = str(text or "").lower()
    if any(token in value for token in ("fix", "bug", "hotfix", "修复", "问题", "缺陷", "故障")):
        return "fix"
    if any(token in value for token in ("feat", "feature", "implement", "实现", "功能", "新增")):
        return "feature"
    if any(token in value for token in ("chore", "docs", "refactor", "test:", "对齐", "升级", "文档")):
        return "chore"
    return "change"


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
TERMINAL_TASK_STATES = frozenset({"completed", "abandoned"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


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


def _matching_event(
    manifest,
    digest: str,
    event_type: str,
    task_id: str,
    *,
    events_by_digest: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    if events_by_digest is None:
        events_by_digest = {str(item["event_digest"]): item for item in read_events(manifest.ledger_path)}
    event = events_by_digest.get(digest)
    if event is None or event.get("event_type") != event_type or event.get("payload", {}).get("task_id") != task_id:
        return None
    return event


def _verification_evidence_valid(
    manifest,
    task: dict[str, Any],
    verification: dict[str, Any],
    *,
    events_by_digest: dict[str, dict[str, Any]] | None = None,
) -> bool:
    event = _matching_event(
        manifest,
        str(verification.get("ledger_event_digest", "")),
        "task-verification",
        str(task["id"]),
        events_by_digest=events_by_digest,
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
        events_by_digest=events_by_digest,
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


def _start_evidence_valid(
    manifest,
    task: dict[str, Any],
    *,
    events_by_digest: dict[str, dict[str, Any]] | None = None,
) -> bool:
    event = _matching_event(
        manifest,
        str(task.get("start_ledger_event_digest", "")),
        "task-started",
        str(task["id"]),
        events_by_digest=events_by_digest,
    )
    if event is None:
        return False
    started_head = task.get("source", {}).get("started_head") or task.get("source", {}).get("head")
    expected = {
        "task_id": task["id"],
        "goal": task.get("goal"),
        "source_head": started_head,
        "source_branch": task.get("source", {}).get("started_branch") or task.get("source", {}).get("branch"),
        "worktree": task.get("worktree", {}).get("path"),
        "worktree_branch": task.get("worktree", {}).get("branch"),
        "slice_digest": task.get("route", {}).get("slice_digest"),
        "route_state": task.get("route", {}).get("state"),
    }
    # Tasks started before the result gate existed have no portrait in the
    # start event; only bind it when the event carries one.
    if "portrait" in event["payload"]:
        expected["portrait"] = task.get("portrait")
    return event["payload"] == expected


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


def _assert_retirement_diff(canonical: Path, worktree: Path, task: dict[str, Any], changed_paths: list[str]) -> None:
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
    for path in deleted:
        owners = households_covering_path(report, "app", path)
        if not owners:
            raise AG2CError(f"cannot-delete-unowned:{path}")
        for household in owners:
            declaration = household.get("jurisdiction") or {}
            identity = str(household.get("identity") or "")
            status = str(declaration.get("status") or "")
            if status == "current" and identity not in {"leftover"}:
                raise AG2CError(f"cannot-delete-active-household:{household['id']}:{path}")
            if status == "legacy" and not household.get("replaced_by"):
                raise AG2CError(f"cannot-delete-without-replacement:{household['id']}")
            if declaration.get("decider") == "confirm" and household["id"] not in confirms:
                raise AG2CError(f"retirement-confirm-required:{household['id']}")
            if open_ids:
                raise AG2CError("cannot-delete-while-tasks-open:" + ",".join(open_ids))
    for path in changed_paths:
        owners = households_covering_path(report, "app", path)
        if owners and not any(str(item["id"]) in leftover_ids for item in owners):
            raise AG2CError(f"retirement-diff-touches-active:{path}")
    hits = scan_references(worktree, deleted, set(deleted))
    if hits:
        raise AG2CError("retirement-references:\n- " + "\n- ".join(hits[:20]))


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


_PORTRAIT_MIN_CHARS = 60

# A portrait must declare HOW its done-states will be checked (the
# verification layer), not only WHAT will be true.
_PORTRAIT_LAYER_MARKERS = (
    "机器验证",
    "实机",
    "用户确认",
    "验证",
    "测试",
    "输出",
    "截图",
    "断言",
    "点击",
    "assert",
    "test",
    "verify",
    "verified",
    "exit",
    "screenshot",
    "output",
)

# Vague phrases can never serve as acceptance criteria. A negated use
# ("不再是…", "不…") is a checkable anti-claim and stays legal.
_PORTRAIT_VAGUE_PHRASES = (
    "正常工作",
    "没有问题",
    "没问题",
    "正常运行",
    "正常显示",
    "能用",
    "好用",
    "优化",
    "完善",
    "合理",
    "works as expected",
    "work as expected",
    "works correctly",
    "works properly",
    "as expected",
    "no issues",
    "it works",
)


def lint_portrait(portrait: str) -> list[str]:
    """Result-gate lint: reject portraits an outsider could never check.

    Three rules, each returning a named violation:
    - too-thin: under _PORTRAIT_MIN_CHARS of substance;
    - no-verification-layer: no marker saying how done-states get checked;
    - vague-phrase: a weasel phrase used as a claim (negations exempt).
    """
    violations: list[str] = []
    text = portrait.strip()
    if len(text) < _PORTRAIT_MIN_CHARS:
        violations.append(f"too-thin: portrait has {len(text)} chars, need at least {_PORTRAIT_MIN_CHARS}")
    lowered = text.lower()
    if not any(marker in text or marker in lowered for marker in _PORTRAIT_LAYER_MARKERS):
        violations.append(
            "no-verification-layer: declare how each done-state gets checked "
            "(机器验证 / 实机 / 用户确认 / 测试 / 输出 / assert / test / verify ...)"
        )
    for phrase in _PORTRAIT_VAGUE_PHRASES:
        start = 0
        haystack = lowered if phrase.isascii() else text
        while True:
            index = haystack.find(phrase, start)
            if index < 0:
                break
            prefix = haystack[max(0, index - 5) : index]
            if not any(neg in prefix for neg in ("不", "no ", "not ", "n't")):
                violations.append(f"vague-phrase: '{phrase}' is not a checkable claim; state what an outsider can verify")
                break
            start = index + len(phrase)
    return violations


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
    if not path_specs and not contract_specs and not all_mode:
        raise AG2CError("AG2C requires exact paths/contracts or conservative --all before work begins")
    try:
        _refuse_household_debt(canonical, path_specs, all_mode)
    except AG2CError as exc:
        _notify_gate_block(canonical, "gate-block", "房间债务拦截", str(exc)[:200])
        raise
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
            "portrait": task["portrait"],
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

    return {**task, "guidance": retrieve_guidance(canonical, path_specs=path_specs, contract_specs=contract_specs, goal=goal, all_mode=all_mode)}


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
    _assert_retirement_diff(canonical, worktree, task, actual_paths)
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
        and all(item["status"] in PROCESS_CHECK_STATUSES for item in report["results"])
        and any(item["status"] == "passed" for item in report["results"])
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


def finish_task(start: Path, task_id: str, *, message: str, proof: str = "") -> dict[str, Any]:
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
        {"task_id": task_id, **task["result"], "proof": task["proof"], "intervention_count": len(task["interventions"])},
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
    task["hints"] = _finish_hints(manifest, policy, pending)
    from .journal import mark_version

    journal = mark_version(canonical, task=task)
    task["journal_version"] = journal["version"]
    _atomic_json(_task_path(canonical, task_id), task)
    return task


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


ORIENT_SCHEMA = "ag2c.orient.v1"


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
        "product": assess_product(
            policy,
            knowledge=knowledge_rows,
            verification=(summaries[0].get("verifications") or [None])[-1] if summaries else None,
            census=census,
        ),
        "tasks": summaries,
    }
