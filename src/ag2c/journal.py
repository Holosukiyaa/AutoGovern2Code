from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import load_manifest, load_policy
from .errors import AG2CError
from .gitops import repository_root
from .ledger import read_events, verify_ledger
from .storage import registered_manifest

JOURNAL_SCHEMA = "ag2c.journal.v1"
JOURNAL_FILENAME = "journals.json"
GOVERNANCE_EVENT_TYPES = frozenset(
    {
        "governance-applied",
        "governance-ingested",
        "governance-settled",
        "knowledge-sync",
        "task-completed",
    }
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def journal_path(manifest) -> Path:
    return manifest.state_dir / JOURNAL_FILENAME


def resolve_journal_manifest(start: Path):
    from .storage import configured_manifest

    root = repository_root(start)
    manifest_path = configured_manifest(root) or registered_manifest(root)
    if manifest_path is None or not manifest_path.is_file():
        raise AG2CError("cannot find AG2C project store for governance journals")
    return load_manifest(manifest_path, project_root=root)


def _card_snapshot(policy) -> list[dict[str, str]]:
    return [{"id": card.card_id, "type": card.card_type, "title": card.title} for card in policy.cards]


def _diff_cards(before: list[dict[str, str]], after: list[dict[str, str]]) -> list[dict[str, str]]:
    previous = {item["id"]: item for item in before}
    current = {item["id"]: item for item in after}
    changes: list[dict[str, str]] = []
    for card_id, card in current.items():
        if card_id not in previous:
            changes.append({"action": "add", "id": card_id, "kind": card["type"], "title": card["title"]})
        elif previous[card_id] != card:
            changes.append({"action": "update", "id": card_id, "kind": card["type"], "title": card["title"]})
    for card_id, card in previous.items():
        if card_id not in current:
            changes.append({"action": "remove", "id": card_id, "kind": card["type"], "title": card["title"]})
    return changes


def _event_summary(event: dict[str, Any]) -> str:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    event_type = str(event.get("event_type", ""))
    if event_type == "governance-applied":
        return f"{payload.get('action', '')} {payload.get('kind', '')} {payload.get('id', '')}".strip()
    if event_type == "knowledge-sync":
        return str(payload.get("reason") or payload.get("card_id") or "knowledge-sync")
    if event_type == "governance-settled":
        return str(payload.get("reason") or "governance-settled")
    if event_type == "governance-ingested":
        return str(payload.get("reason") or "governance-ingested")
    if event_type == "task-completed":
        return str(payload.get("task_id") or "task-completed")
    return event_type


def _load_journal(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"schema": JOURNAL_SCHEMA, "versions": []}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AG2CError(f"cannot read governance journal {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") != JOURNAL_SCHEMA:
        raise AG2CError(f"unsupported governance journal: {path}")
    versions = value.get("versions")
    if not isinstance(versions, list):
        raise AG2CError(f"governance journal has an invalid version list: {path}")
    return value


def list_journals(start: Path) -> list[dict[str, Any]]:
    manifest = resolve_journal_manifest(start)
    return list(_load_journal(journal_path(manifest)).get("versions") or [])


def mark_version(start: Path, *, task: dict[str, Any]) -> dict[str, Any]:
    root = repository_root(start)
    manifest = resolve_journal_manifest(root)
    policy = load_policy(manifest)
    path = journal_path(manifest)
    document = _load_journal(path)
    versions = list(document.get("versions") or [])
    previous = versions[-1] if versions else None
    current_cards = _card_snapshot(policy)
    previous_cards = list((previous or {}).get("cards") or [])
    after_sequence = int((previous or {}).get("ledger_sequence") or 0)
    ledger_errors = verify_ledger(manifest.ledger_path)
    events = read_events(manifest.ledger_path) if not ledger_errors else []
    relevant = [
        event
        for event in events
        if int(event.get("sequence") or 0) > after_sequence and event.get("event_type") in GOVERNANCE_EVENT_TYPES
    ]
    ledger_changes = [
        {
            "action": str((event.get("payload") or {}).get("action") or event.get("event_type")),
            "id": str((event.get("payload") or {}).get("id") or (event.get("payload") or {}).get("card_id") or ""),
            "kind": str((event.get("payload") or {}).get("kind") or event.get("event_type")),
            "title": str((event.get("payload") or {}).get("reason") or ""),
        }
        for event in relevant
        if event.get("event_type") == "governance-applied"
    ]
    card_changes = _diff_cards(previous_cards, current_cards) if previous else ledger_changes
    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    verification = (task.get("verifications") or [{}])[-1] if task.get("verifications") else {}
    pending = task.get("governance_pending") if isinstance(task.get("governance_pending"), dict) else {}
    version = {
        "version": len(versions) + 1,
        "marked_at": _now(),
        "task_id": task.get("id"),
        "goal": task.get("goal"),
        "outcome": (task.get("delivery") or {}).get("outcome") if isinstance(task.get("delivery"), dict) else "",
        "kind": (task.get("delivery") or {}).get("kind") if isinstance(task.get("delivery"), dict) else "",
        "commit": result.get("commit") or result.get("merged_head"),
        "card_changes": card_changes,
        "cards": current_cards,
        "events": [
            {
                "type": event.get("event_type"),
                "occurred_at": event.get("occurred_at"),
                "summary": _event_summary(event),
            }
            for event in relevant
        ],
        "changed_paths": list(verification.get("changed_paths") or []),
        "pending_count": len(pending.get("items") or []),
        "ledger_sequence": int(events[-1]["sequence"]) if events else after_sequence,
    }
    versions.append(version)
    _atomic_json(path, {"schema": JOURNAL_SCHEMA, "versions": versions})
    return version
