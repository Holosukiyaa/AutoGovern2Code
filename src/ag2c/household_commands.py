"""Audited mutations for directory cards and explicit census reviews."""
from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from .config import discover_manifest, load_manifest, load_policy
from .errors import AG2CError
from .gitops import repository_root
from .govern import _atomic_json, _read_json
from .households import (
    RECORD_BLOCK_ISSUES,
    RENEWAL_SCHEMA,
    _history,
    assert_monotonic,
    census_path,
    census_report,
    coerce_jurisdiction,
    directory_scope,
    load_renewals,
    renewal_path,
)
from .index import build_index
from .ledger import _exclusive_lock, append_event
from .util import digest_json


def _context(start: Path):
    root = repository_root(start)
    manifest = load_manifest(discover_manifest(root), project_root=root)
    return manifest, load_policy(manifest)


def _identity(actor: str, reason: str) -> tuple[str, str]:
    if not actor.strip() or not reason.strip():
        raise AG2CError("household governance requires --actor and --reason")
    return actor.strip(), reason.strip()


def _save_policy(manifest, raw: dict, actor: str, reason: str, event_type: str, payload: dict, after_load=None) -> dict:
    temporary = manifest.policy_path.with_name(f".households-{uuid.uuid4().hex}.json")
    try:
        _atomic_json(temporary, raw)
        loaded = load_policy(replace(manifest, policy_path=temporary))
        if after_load is not None:
            after_load(replace(manifest, policy_path=temporary), loaded)
        temporary.replace(manifest.policy_path)
    finally:
        temporary.unlink(missing_ok=True)
    build_index(manifest, load_policy(manifest))
    event = append_event(manifest.ledger_path, event_type, {**payload, "actor": actor, "reason": reason})
    return {**payload, "actor": actor, "reason": reason, "ledger_event_digest": event["event_digest"]}


def register_household(start: Path, *, card_id: str, title: str, summary: str, includes: list[str], excludes: list[str], floors: list[str], capability: str, implementation: str, status: str, replaced_by: str = "", entrypoints: list[str] | None = None, checkers: list[str] | None = None, command: list[str] | None = None, grain: str = "", meaning: str = "", contract: str = "", decider: str = "", actor: str, reason: str) -> dict:
    actor, reason = _identity(actor, reason)
    manifest, policy = _context(start)
    raw = _read_json(manifest.policy_path)
    if not includes or not title.strip() or not summary.strip():
        raise AG2CError("directory household requires title, summary and directory scopes")
    for pattern in (*includes, *excludes):
        directory_scope(pattern)
    known = {card.card_id: card for card in policy.cards}
    if card_id in known and (known[card_id].card_type != "knowledge" or known[card_id].jurisdiction is None):
        raise AG2CError("cannot silently convert a document or floor into a directory household")
    if not floors or any(floor not in known or known[floor].card_type != "floor" for floor in floors):
        raise AG2CError("household requires existing floor links")
    selected_checkers = list(dict.fromkeys(checkers or []))
    if command is not None:
        if not command or any(not isinstance(item, str) or not item for item in command):
            raise AG2CError("checker command must be a nonempty JSON array of strings")
        checker_id = f"check.{card_id}"
        previous = next((item for item in raw.get("checkers", []) if item["id"] == checker_id), None)
        if previous and previous.get("implementation") != implementation:
            raise AG2CError("cannot rebind an existing implementation checker")
        checker = {"id": checker_id, "stage": "scenario", "target": "app", "cwd": ".", "command": command, "timeout": 600, "implementation": implementation}
        raw["checkers"] = [item for item in raw.get("checkers", []) if item["id"] != checker_id] + [checker]
        selected_checkers.append(checker_id)
    card = {"id": card_id, "type": "knowledge", "title": title.strip(), "summary": summary.strip(), "scopes": [{"target": "app", "include": includes, "exclude": excludes, "ownership": "reference"}], "references": [], "checkers": list(dict.fromkeys(selected_checkers)), "jurisdiction": {"capability": capability, "implementation": implementation, "status": status, "entrypoints": list(entrypoints or []), "grain": grain or "subtree", "meaning": meaning or "none", "contract": contract or "none", "decider": decider or "none"}}
    raw["cards"] = [item for item in raw.get("cards", []) if item["id"] != card_id] + [card]
    raw["relations"] = [item for item in raw.get("relations", []) if not (item["source"] == card_id and item["type"] in {"explains", "replaced_by"})]
    raw["relations"].extend({"source": card_id, "type": "explains", "target": floor} for floor in floors)
    if replaced_by:
        raw["relations"].append({"source": card_id, "type": "replaced_by", "target": replaced_by})
    return _save_policy(manifest, raw, actor, reason, "household-registered", {"id": card_id, "summary": summary, "jurisdiction": card["jurisdiction"], "scopes": card["scopes"]})


def review_census(start: Path, *, card_ids: list[str], all_cards: bool, actor: str, reason: str) -> dict:
    manifest, _policy = _context(start)
    with _exclusive_lock(census_path(manifest)):
        return _review_census_locked(start, card_ids=card_ids, all_cards=all_cards, actor=actor, reason=reason)


def _review_census_locked(start: Path, *, card_ids: list[str], all_cards: bool, actor: str, reason: str) -> dict:
    actor, reason = _identity(actor, reason)
    manifest, policy = _context(start)
    report = census_report(manifest, policy)
    chosen = {item["id"] for item in report["households"]} if all_cards else set(card_ids)
    if not chosen or chosen - {item["id"] for item in report["households"]}:
        raise AG2CError("census review requires known household or floor ids, or --all")
    blocked = []
    for item in report["households"]:
        if item["id"] not in chosen:
            continue
        codes = {str(issue.get("code")) for issue in item.get("issues") or []}
        blocked_codes = sorted(codes & RECORD_BLOCK_ISSUES)
        if blocked_codes:
            blocked.append(f'{item["id"]}:{",".join(blocked_codes)}')
    if blocked:
        raise AG2CError("census-record-blocked:\n- " + "\n- ".join(blocked))
    state = _history(manifest)
    batch = uuid.uuid4().hex
    timestamp = datetime.now(timezone.utc).isoformat()
    additions = []
    for item in report["households"]:
        if item["id"] not in chosen:
            continue
        record = {"id": f'{batch}:{item["id"]}', "card_id": item["id"], "surveyed_at": timestamp, "actor": actor, "reason": reason, "summary": item["summary"], "scope_digest": item["scope_digest"], "declaration_digest": item["declaration_digest"], "scopes": item["scopes"], "file_count": item["file_count"], "code_count": item["code_count"], "project_revisions": report["revisions"], "known_issues": item["issues"], "previous": next((entry["id"] for entry in reversed(state["records"]) if entry["card_id"] == item["id"]), None)}
        record["last_source_change"] = item["last_source_change"]
        record["digest"] = digest_json(record)
        additions.append(record)
    state["records"].extend(additions)
    event = append_event(manifest.ledger_path, "census-reviewed", {"actor": actor, "reason": reason, "records": additions})
    _atomic_json(census_path(manifest), state)
    return {"actor": actor, "reason": reason, "reviewed": sorted(chosen), "ledger_event_digest": event["event_digest"], "census": census_report(manifest, policy)}


def tighten_household(
    start: Path,
    *,
    card_id: str,
    grain: str = "",
    meaning: str = "",
    contract: str = "",
    decider: str = "",
    actor: str,
    reason: str,
) -> dict:
    actor, reason = _identity(actor, reason)
    card_id = card_id.strip()
    if not any(value.strip() for value in (grain, meaning, contract, decider)):
        raise AG2CError("tighten requires at least one of grain, meaning, contract, or decider")
    manifest, policy = _context(start)
    card = next((item for item in policy.cards if item.card_id == card_id), None)
    if card is None or card.jurisdiction is None:
        raise AG2CError(f"unknown directory household: {card_id}")
    old = coerce_jurisdiction(card.jurisdiction) or {}
    new = dict(old)
    if grain.strip():
        new["grain"] = grain.strip()
    if meaning.strip():
        new["meaning"] = meaning.strip()
    if contract.strip():
        new["contract"] = contract.strip()
    if decider.strip():
        new["decider"] = decider.strip()
    assert_monotonic(old, new)
    raw = _read_json(manifest.policy_path)
    found = False
    for item in raw.get("cards", []):
        if item.get("id") != card_id:
            continue
        item["jurisdiction"] = {**(item.get("jurisdiction") or {}), **new}
        found = True
        break
    if not found:
        raise AG2CError(f"unknown directory household: {card_id}")

    def refuse_opaque(loaded_manifest, loaded_policy) -> None:
        report = census_report(loaded_manifest, loaded_policy)
        record = next((item for item in report["households"] if item["id"] == card_id), None)
        if record is None:
            raise AG2CError(f"unknown directory household: {card_id}")
        blocked = sorted({str(issue.get("code")) for issue in record.get("issues") or []} & RECORD_BLOCK_ISSUES)
        if blocked:
            raise AG2CError("tighten-blocked:\n- " + "\n- ".join(f"{card_id}:{code}" for code in blocked))

    result = _save_policy(
        manifest,
        raw,
        actor,
        reason,
        "household-tightened",
        {"id": card_id, "previous": old, "jurisdiction": new},
        after_load=refuse_opaque,
    )
    from .govern import pending_updates

    pending_updates(start)
    report = census_report(*_context(start))
    result["identity"] = next(item["identity"] for item in report["households"] if item["id"] == card_id)
    return result


def renew_exploring(start: Path, *, card_id: str, actor: str, reason: str) -> dict:
    actor, reason = _identity(actor, reason)
    card_id = card_id.strip()
    manifest, policy = _context(start)
    report = census_report(manifest, policy)
    record = next((item for item in report["households"] if item["id"] == card_id), None)
    if record is None or not record.get("jurisdiction"):
        raise AG2CError(f"unknown directory household: {card_id}")
    if record.get("identity") != "exploring":
        raise AG2CError(f"renew-exploring only applies to exploring households: {card_id} is {record.get('identity')}")
    children = list(record.get("child_directories") or [])
    cards = load_renewals(manifest)
    cards[card_id] = {
        "renewed_at": datetime.now(timezone.utc).isoformat(),
        "actor": actor,
        "reason": reason,
        "child_directories": children,
    }
    _atomic_json(renewal_path(manifest), {"schema": RENEWAL_SCHEMA, "cards": cards})
    event = append_event(
        manifest.ledger_path,
        "exploring-renewed",
        {"id": card_id, "actor": actor, "reason": reason, "child_directories": children, "identity": "exploring"},
    )
    from .govern import pending_updates

    pending = pending_updates(start)
    return {
        "id": card_id,
        "identity": "exploring",
        "actor": actor,
        "reason": reason,
        "child_directories": children,
        "pending": pending.get("items") or [],
        "ledger_event_digest": event["event_digest"],
    }


def set_household_enforcement(start: Path, *, enabled: bool, actor: str, reason: str) -> dict:
    actor, reason = _identity(actor, reason)
    manifest, _policy = _context(start)
    raw = _read_json(manifest.policy_path)
    raw["household_required"] = enabled
    return _save_policy(manifest, raw, actor, reason, "household-enforcement-changed", {"enabled": enabled})


def read_census(start: Path) -> dict:
    manifest, policy = _context(start)
    return census_report(manifest, policy)
