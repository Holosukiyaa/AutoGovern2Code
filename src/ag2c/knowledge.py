from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import AG2CError, ConfigurationError
from .ledger import append_event
from .model import Card, Manifest, Policy
from .util import atomic_json_write, digest_file, digest_json, normalize_artifact_path


KNOWLEDGE_SCHEMA = "ag2c.knowledge.v1"
KNOWLEDGE_FILENAME = "knowledge.json"


def knowledge_path(manifest: Manifest) -> Path:
    return manifest.state_dir / KNOWLEDGE_FILENAME


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_atomic_json = atomic_json_write


def _read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema": KNOWLEDGE_SCHEMA, "cards": {}}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AG2CError(f"cannot read Knowledge state {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") != KNOWLEDGE_SCHEMA:
        raise AG2CError(f"Knowledge state schema must be {KNOWLEDGE_SCHEMA}: {path}")
    cards = value.get("cards", {})
    if not isinstance(cards, dict):
        raise AG2CError(f"Knowledge state cards must be an object: {path}")
    return value


def _target_ids(manifest: Manifest, card: Card) -> tuple[str, ...]:
    scoped = {scope.target_id for scope in card.scopes}
    return tuple(target.target_id for target in manifest.targets if not scoped or target.target_id in scoped)


def _reference_path(manifest: Manifest, target_id: str, reference: str) -> tuple[str, Path] | None:
    normalized = reference.replace("\\", "/").strip()
    explicit_target, separator, explicit_path = normalized.partition(":")
    if separator and explicit_target in {target.target_id for target in manifest.targets}:
        target_id, normalized = explicit_target, explicit_path
    try:
        normalized = normalize_artifact_path(normalized)
    except ConfigurationError:
        return None
    path = (manifest.target_root(target_id) / normalized).resolve()
    try:
        path.relative_to(manifest.target_root(target_id))
    except ValueError:
        return None
    return f"{target_id}:{normalized}", path


def _normalize_claim(value: str) -> str:
    return " ".join(value.split())


def _lead_claim(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    for line in text.splitlines():
        claim = _normalize_claim(line.lstrip("#").strip())
        if claim:
            return claim[:180]
    return ""


def _assertions_from_files(manifest: Manifest, card: Card) -> list[dict[str, str]]:
    assertions: list[dict[str, str]] = []
    seen: set[str] = set()
    for reference in card.references:
        explicit_target, separator, _ = reference.replace("\\", "/").strip().partition(":")
        target_ids = (
            (explicit_target,)
            if separator and explicit_target in {target.target_id for target in manifest.targets}
            else _target_ids(manifest, card)
        )
        for target_id in target_ids:
            resolved = _reference_path(manifest, target_id, reference)
            if resolved is None:
                continue
            qualified, path = resolved
            if qualified in seen or not path.is_file():
                continue
            seen.add(qualified)
            claim = _lead_claim(path)
            if claim:
                assertions.append({"id": f"lead:{qualified}", "text": claim, "reference": qualified})
    assertions.sort(key=lambda item: item["id"])
    return assertions


def _assertion_status(manifest: Manifest, saved: dict[str, Any] | None) -> tuple[str, list[str], list[dict[str, str]]]:
    if not isinstance(saved, dict):
        return "unknown", [], []
    stored = saved.get("assertions")
    if not isinstance(stored, list) or not stored:
        return "unknown", [], []
    reasons: list[str] = []
    current: list[dict[str, str]] = []
    for item in stored:
        if not isinstance(item, dict):
            continue
        assertion_id = str(item.get("id") or "summary")
        expected = _normalize_claim(str(item.get("text") or ""))
        reference = str(item.get("reference") or "")
        target_id, separator, relative = reference.partition(":")
        lead = ""
        if separator:
            resolved = _reference_path(manifest, target_id, relative)
            if resolved is not None and resolved[1].is_file():
                lead = _lead_claim(resolved[1])
        if not expected:
            continue
        if not lead:
            reasons.append(f"assertion-missing:{assertion_id}")
            current.append({"id": assertion_id, "text": expected, "reference": reference, "status": "missing"})
        elif lead != expected:
            reasons.append(f"assertion-changed:{assertion_id}")
            current.append({"id": assertion_id, "text": expected, "observed": lead, "reference": reference, "status": "conflict"})
        else:
            current.append({"id": assertion_id, "text": expected, "reference": reference, "status": "current"})
    if not current:
        return "unknown", [], []
    return ("conflict" if reasons else "current"), reasons, current


def _anchor_for_card(manifest: Manifest, card: Card) -> dict[str, Any]:
    references: list[dict[str, Any]] = []
    for reference in card.references:
        explicit_target, separator, _ = reference.replace("\\", "/").strip().partition(":")
        target_ids = (
            (explicit_target,)
            if separator and explicit_target in {target.target_id for target in manifest.targets}
            else _target_ids(manifest, card)
        )
        candidates = [_reference_path(manifest, target_id, reference) for target_id in target_ids]
        candidates = [item for item in candidates if item is not None]
        if not candidates:
            references.append({"reference": reference, "status": "unknown"})
            continue
        for qualified, path in candidates:
            if path.is_file():
                references.append(
                    {"reference": qualified, "status": "current", "digest": digest_file(path)}
                )
            else:
                references.append({"reference": qualified, "status": "missing"})
    references.sort(key=lambda item: str(item["reference"]))
    return {
        "card_id": card.card_id,
        "references": references,
        "anchor_digest": digest_json(references),
    }


def _status_for_card(state: dict[str, Any], anchor: dict[str, Any], *, manifest: Manifest) -> dict[str, Any]:
    saved = state.get("cards", {}).get(anchor["card_id"])
    if not anchor["references"]:
        return {
            "id": anchor["card_id"],
            "source_status": "unknown",
            "assertion_status": "unknown",
            "status": "unknown",
            "anchor_digest": None,
            "current_digest": anchor["anchor_digest"],
            "reasons": ["no-references"],
            "references": anchor["references"],
            "assertions": [],
        }
    if not isinstance(saved, dict) or not saved.get("anchor_digest"):
        return {
            "id": anchor["card_id"],
            "source_status": "unknown",
            "assertion_status": "unknown",
            "status": "unknown",
            "anchor_digest": None,
            "current_digest": anchor["anchor_digest"],
            "reasons": ["not-synced"],
            "references": anchor["references"],
            "assertions": [],
        }
    reasons: list[str] = []
    if any(item.get("status") in {"missing", "unknown"} for item in anchor["references"]):
        reasons.append("reference-missing")
    if str(saved.get("anchor_digest")) != anchor["anchor_digest"]:
        reasons.append("reference-digest-changed")
    source_status = "stale" if reasons else "current"
    assertion_status, assertion_reasons, assertions = _assertion_status(manifest, saved)
    reasons.extend(assertion_reasons)
    if assertion_status == "conflict":
        status = "conflict"
    elif source_status == "stale":
        status = "stale"
    else:
        status = "current"
    return {
        "id": anchor["card_id"],
        "source_status": source_status,
        "assertion_status": assertion_status,
        "status": status,
        "anchor_digest": saved.get("anchor_digest"),
        "current_digest": anchor["anchor_digest"],
        "reasons": reasons,
        "references": anchor["references"],
        "assertions": assertions,
    }


def knowledge_status(manifest: Manifest, policy: Policy) -> list[dict[str, Any]]:
    state = _read_state(knowledge_path(manifest))
    statuses: list[dict[str, Any]] = []
    jurisdictions = {}
    if any(card.jurisdiction is not None for card in policy.cards):
        from .households import census_report

        jurisdictions = {item["id"]: item for item in census_report(manifest, policy)["households"] if item["jurisdiction"]}
    for card in policy.cards:
        if card.card_type != "knowledge":
            continue
        if card.card_id in jurisdictions:
            record = jurisdictions[card.card_id]
            freshness = record["freshness"] if record["freshness"] != "never" else "unknown"
            statuses.append({"id": card.card_id, "title": card.title, "target_ids": list(_target_ids(manifest, card)), "status": freshness, "source_status": freshness, "assertion_status": "current", "reasons": [] if freshness == "current" else ["census-review-required"], "references": [], "assertions": [], "jurisdiction": True, "anchor_digest": (record["last_census"] or {}).get("scope_digest"), "current_digest": record["scope_digest"]})
            continue
        status = _status_for_card(state, _anchor_for_card(manifest, card), manifest=manifest)
        status.update({"title": card.title, "target_ids": list(_target_ids(manifest, card))})
        statuses.append(status)
    return statuses


def sync_knowledge(
    manifest: Manifest,
    policy: Policy,
    *,
    card_ids: list[str],
    actor: str,
    reason: str,
) -> dict[str, Any]:
    actor = actor.strip()
    reason = reason.strip()
    if not actor:
        raise AG2CError("Knowledge sync requires --actor")
    if not reason:
        raise AG2CError("Knowledge sync requires --reason")
    if not card_ids:
        raise AG2CError("Knowledge sync requires at least one --card")
    requested = list(dict.fromkeys(card_ids))
    cards = {card.card_id: card for card in policy.cards if card.card_type == "knowledge"}
    unknown = sorted(set(requested) - set(cards))
    if unknown:
        raise AG2CError("unknown Knowledge card(s): " + ", ".join(unknown))
    state = _read_state(knowledge_path(manifest))
    current: dict[str, Any] = {}
    previous: dict[str, Any] = {}
    for card_id in requested:
        anchor = _anchor_for_card(manifest, cards[card_id])
        status = _status_for_card(state, anchor, manifest=manifest)
        if not anchor["references"] or any(item.get("status") in {"missing", "unknown"} for item in anchor["references"]):
            raise AG2CError(f"Knowledge card has missing or invalid references: {card_id}")
        current[card_id] = {**anchor, "assertions": _assertions_from_files(manifest, cards[card_id])}
        previous[card_id] = status.get("anchor_digest")
    updated = dict(state)
    updated["updated_at"] = _now()
    saved_cards = dict(updated.get("cards", {}))
    for card_id, anchor in current.items():
        saved_cards[card_id] = {
            "anchor_digest": anchor["anchor_digest"],
            "references": anchor["references"],
            "assertions": anchor["assertions"],
            "synced_at": updated["updated_at"],
        }
    updated["cards"] = saved_cards
    _atomic_json(knowledge_path(manifest), updated)
    event = append_event(
        manifest.ledger_path,
        "knowledge-sync",
        {
            "project_id": manifest.project_id,
            "cards": requested,
            "actor": actor,
            "reason": reason,
            "previous_anchor_digests": previous,
            "anchor_digests": {card_id: anchor["anchor_digest"] for card_id, anchor in current.items()},
        },
    )
    return {
        "schema": KNOWLEDGE_SCHEMA,
        "cards": requested,
        "actor": actor,
        "reason": reason,
        "statuses": knowledge_status(manifest, policy),
        "ledger_event_digest": event["event_digest"],
    }
