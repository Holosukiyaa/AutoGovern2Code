"""6.1 政策沙盘：只读重放候选规则。不写 policy，不追加账本。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import AG2CError
from .ledger import read_events

SANDBOX_SCHEMA = "ag2c.sandbox.v1"
SCENARIO_L2_TO_L3 = "l2-to-l3"
_COMPLETED = frozenset({"task-completed"})
_FAILED = frozenset({"verification-failed"})


def _card_ids(payload: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    cards = payload.get("cards")
    if isinstance(cards, list):
        ids.extend(str(item) for item in cards if item)
    for key in ("card_id", "id", "path"):
        value = payload.get(key)
        if isinstance(value, str) and value.startswith("knowledge."):
            ids.append(value)
    return ids


def sandbox_replay(ledger_path: Path, *, scenario: str) -> dict[str, Any]:
    """AG2K L2→L3 分拣：careful = 有成功引用且无失败引用；naive = 任意引用。"""
    if scenario != SCENARIO_L2_TO_L3:
        raise AG2CError(f"unknown sandbox scenario: {scenario}")
    events = read_events(ledger_path) if ledger_path.exists() else []
    completed: set[str] = set()
    failed: set[str] = set()
    for event in events:
        ids = _card_ids(event.get("payload") or {})
        kind = str(event.get("event_type") or "")
        if kind in _COMPLETED:
            completed.update(ids)
        elif kind in _FAILED:
            failed.update(ids)
    careful = completed - failed
    naive = completed | failed
    return {
        "schema": SANDBOX_SCHEMA,
        "scenario": scenario,
        "would_block": sorted(naive - careful),
        "would_false_positive": sorted(naive - careful),
        "eligible": sorted(careful),
        "read_only": True,
    }


def run_sandbox(start: Path, *, scenario: str) -> dict[str, Any]:
    from .config import discover_manifest, load_manifest
    from .gitops import repository_root

    root = repository_root(start)
    manifest = load_manifest(discover_manifest(root), project_root=root)
    return sandbox_replay(manifest.ledger_path, scenario=scenario)
