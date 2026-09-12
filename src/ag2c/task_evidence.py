"""Extracted by flatten-split."""
from __future__ import annotations
import hashlib
from typing import Any

from .ledger import read_events

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
        # None for verifications recorded before agent-review existed; the
        # subset match below reads a missing payload key as None, so old
        # events still bind while new ones bind the regulator verdict exactly.
        "regulator": verification.get("regulator"),
    }
    # Forward compatibility: the ledger event digest covers the whole payload,
    # so keys this validator does not know cannot be forged after the fact.
    # Bind every known key exactly; tolerate extensions recorded by newer
    # versions (e.g. regulator verdicts) so older canonical code can still
    # finish tasks verified by newer worktree code.
    if any(payload.get(key) != value for key, value in expected.items()):
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
    # 只比对 4 个稳定键：duration_ms 等信息性字段允许存在但不参与证据绑定，
    # 这样新旧版本验证记录互相兼容（duration_ms 无安全语义，绑定它只会制造版本偏斜）。
    evidence_keys = ("id", "stage", "status", "exit_code")
    actual_results = [
        {key: item.get(key) for key in evidence_keys}
        for item in check_event["payload"].get("results", [])
    ]
    recorded_results = [
        {key: item.get(key) for key in evidence_keys}
        for item in verification.get("checker_results") or []
    ]
    return (
        recorded_results == actual_results
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
    # start event; only bind it when the event carries one. Same conditional
    # binding for coordinates (added after the gate): tasks started before the
    # coordinate declaration existed carry no coordinates key and stay valid.
    if "portrait" in event["payload"]:
        expected["portrait"] = task.get("portrait")
    if "coordinates" in event["payload"]:
        expected["coordinates"] = task.get("coordinates")
    if event["payload"] == expected:
        return True
    # 画像修订（amend-portrait）是合法的画像迁移通道：start 事件锚定的是修订
    # 前画像，finish 时当前画像可以经账本锚定的修订链合法迁移。没有这条通道，
    # 任何修订过画像的任务都死在 finish（2026-09-11 实战：任务 2 verify 通过后
    # 被 start 证据门禁误拦）。修订的合法性（市长纠偏 vs 自利漂移）由 verify
    # 时的监管裁决，这里只验链的完整性，不做二次裁决。
    if "portrait" not in event["payload"]:
        return False
    baseline = dict(expected)
    baseline["portrait"] = event["payload"].get("portrait")
    if event["payload"] != baseline:
        # 画像以外的字段不一致，修订链不背锅。
        return False
    return _portrait_amendment_chain_valid(
        manifest, task, event["payload"]["portrait"], events_by_digest=events_by_digest
    )

def _portrait_amendment_chain_valid(
    manifest,
    task: dict[str, Any],
    original_portrait: Any,
    *,
    events_by_digest: dict[str, dict[str, Any]] | None = None,
) -> bool:
    """start 事件画像 → 当前画像 的修订链校验：环环相扣且每环都有账本锚。

    链规则：sha256(start 事件画像) == 首环 old_digest，每环 new_digest 是下一环
    的 old_digest，末环 new_digest == sha256(当前画像)；每环 intervention 的
    ledger_event_digest 必须在账本中找到 kind/old_digest/new_digest 一致的
    governance-intervention 事件——账本是 append-only，锚住才算数，task JSON
    里手写一个 intervention 骗不过。
    """
    if events_by_digest is None:
        events_by_digest = {str(item["event_digest"]): item for item in read_events(manifest.ledger_path)}
    amendments = [item for item in task.get("interventions", []) if isinstance(item, dict) and item.get("kind") == "portrait-amended"]
    if not amendments:
        return False
    expected_old = hashlib.sha256(str(original_portrait).encode("utf-8")).hexdigest()
    for item in amendments:
        if str(item.get("old_digest", "")) != expected_old:
            return False
        anchor = _matching_event(
            manifest,
            str(item.get("ledger_event_digest", "")),
            "governance-intervention",
            str(task["id"]),
            events_by_digest=events_by_digest,
        )
        if anchor is None:
            return False
        payload = anchor["payload"]
        if (
            payload.get("kind") != "portrait-amended"
            or payload.get("old_digest") != item.get("old_digest")
            or payload.get("new_digest") != item.get("new_digest")
        ):
            return False
        expected_old = str(item.get("new_digest", ""))
    current = hashlib.sha256(str(task.get("portrait") or "").encode("utf-8")).hexdigest()
    return expected_old == current
