from __future__ import annotations

import sqlite3
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from .config import load_policy
from .errors import ConfigurationError, SliceError
from .index import index_path, primary_owners, summary as index_summary, verify_freshness
from .knowledge import knowledge_status
from .model import Card, Manifest, Policy, Scope
from .util import digest_file, digest_json, normalize_artifact_path, path_matches

SLICE_SCHEMA = "ag2c.slice.v1"
CARD_ORDER = {"constitution": 0, "floor": 1, "boundary": 2, "knowledge": 3, "scenario": 4, "task": 5}


def parse_path_spec(value: str, manifest: Manifest) -> tuple[str, str]:
    target_id, separator, artifact_path = value.partition(":")
    if not separator or target_id not in {target.target_id for target in manifest.targets}:
        raise SliceError(f"path must use target-id:relative/path and reference a configured target: {value}")
    try:
        return target_id, normalize_artifact_path(artifact_path)
    except ConfigurationError as exc:
        raise SliceError(str(exc)) from exc


def parse_contract_spec(value: str, manifest: Manifest) -> tuple[str, str, str]:
    target_id, separator, remainder = value.partition(":")
    contract_id, version_separator, version = remainder.rpartition("@")
    if (
        not separator or not version_separator or not contract_id or not version
        or target_id not in {target.target_id for target in manifest.targets}
    ):
        raise SliceError(f"contract must use target-id:contract-id@version: {value}")
    return target_id, contract_id, version


def _scope_matches(scope: Scope, target_id: str, artifact_path: str) -> bool:
    return (
        scope.target_id == target_id
        and any(path_matches(artifact_path, pattern) for pattern in scope.includes)
        and not any(path_matches(artifact_path, pattern) for pattern in scope.excludes)
    )


def _card_payload(card: Card, reasons: set[str], freshness: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "id": card.card_id,
        "type": card.card_type,
        "title": card.title,
        "summary": card.summary,
        "references": list(card.references),
        "selection_reasons": sorted(reasons),
    }
    if card.card_type == "knowledge" and freshness is not None:
        payload["freshness"] = freshness
    return payload


def compile_slice(
    manifest: Manifest,
    policy: Policy | None = None,
    *,
    path_specs: list[str] | None = None,
    contract_specs: list[str] | None = None,
    goal: str = "",
    all_mode: bool = False,
    index: Path | None = None,
) -> dict[str, Any]:
    policy = policy or load_policy(manifest)
    index = (index or index_path(manifest)).resolve()
    freshness_errors = verify_freshness(manifest, policy, index)
    if freshness_errors:
        raise SliceError("index is not current:\n- " + "\n- ".join(freshness_errors))
    path_specs = path_specs or []
    contract_specs = contract_specs or []
    if not path_specs and not contract_specs and not all_mode:
        raise SliceError("an entry slice requires --path, --contract, or --all; --goal is advisory only")

    reasons: dict[str, set[str]] = defaultdict(set)
    fallback_reasons: list[str] = []
    fallback_targets: set[str] = set()
    artifacts: list[dict[str, str]] = []
    contracts: list[dict[str, str]] = []
    selected_primary: dict[str, set[str]] = defaultdict(set)

    def select(card_id: str, reason: str) -> None:
        reasons[card_id].add(reason)

    def expand_target(target_id: str, reason: str) -> None:
        fallback_targets.add(target_id)
        fallback_reasons.append(reason)
        for card in policy.cards:
            if card.card_type == "floor" and any(scope.target_id == target_id for scope in card.scopes):
                select(card.card_id, f"conservative-target:{target_id}")

    for card in policy.cards:
        if card.card_type == "constitution":
            select(card.card_id, "active-constitution")

    if all_mode:
        for card in policy.cards:
            if card.card_type in {"floor", "boundary", "scenario"}:
                select(card.card_id, "all-mode")

    connection = sqlite3.connect(f"{index.as_uri()}?mode=ro", uri=True)
    try:
        for raw_spec in path_specs:
            target_id, artifact_path = parse_path_spec(raw_spec, manifest)
            artifact_id = f"{target_id}:{artifact_path}"
            row = connection.execute(
                "SELECT artifact_id, content_digest, worktree_state FROM artifact WHERE target_id = ? AND artifact_path = ?",
                (target_id, artifact_path),
            ).fetchone()
            owners = primary_owners(policy, target_id, artifact_path)
            artifacts.append(
                {
                    "id": artifact_id,
                    "target": target_id,
                    "path": artifact_path,
                    "state": str(row[2]) if row else "planned",
                    "content_digest": str(row[1]) if row else "not-indexed",
                }
            )
            if len(owners) == 1:
                select(owners[0].card_id, f"primary-owner:{artifact_id}")
                selected_primary[target_id].add(owners[0].card_id)
            else:
                status = "unowned" if not owners else "ambiguous"
                expand_target(target_id, f"{status}-entry:{artifact_id}")
            for card in policy.cards:
                if card.card_type == "knowledge" and any(
                    _scope_matches(scope, target_id, artifact_path) for scope in card.scopes
                ):
                    select(card.card_id, f"scoped-knowledge:{artifact_id}")
    finally:
        connection.close()

    if not all_mode:
        floors_by_target: dict[str, set[str]] = defaultdict(set)
        for card in policy.cards:
            if card.card_type == "floor":
                for scope in card.scopes:
                    floors_by_target[scope.target_id].add(card.card_id)
        for target_id, selected in selected_primary.items():
            total = floors_by_target.get(target_id, set())
            if len(selected) >= 2 and total and len(selected) * 2 >= len(total):
                expand_target(target_id, f"broad-change:{target_id}")

    for raw_spec in contract_specs:
        target_id, contract_id, version = parse_contract_spec(raw_spec, manifest)
        key = f"{target_id}:{contract_id}@{version}"
        binding = next((item for item in policy.contracts if item.key == key), None)
        contracts.append({"key": key, "status": "bound" if binding else "unknown"})
        if binding is None:
            expand_target(target_id, f"unknown-contract:{key}")
            continue
        select(binding.boundary, f"contract-binding:{key}")
        for scenario in binding.scenarios:
            select(scenario, f"contract-scenario:{key}")
        for relation in policy.relations:
            if relation.source == binding.boundary and relation.relation_type in {"producer", "consumer"}:
                select(relation.target, f"contract-{relation.relation_type}:{key}")

    freshness_by_id = {item["id"]: item for item in knowledge_status(manifest, policy)}
    for card_id, card_reasons in list(reasons.items()):
        card = policy.card(card_id)
        if card.card_type != "knowledge":
            continue
        freshness = freshness_by_id[card_id]
        if freshness["status"] in {"stale", "conflict"}:
            prefix = "conflict-knowledge" if freshness["status"] == "conflict" else "stale-knowledge"
            for target_id in freshness["target_ids"]:
                expand_target(target_id, f"{prefix}:{card_id}")

    # Cards selected up to this point are DIRECT hits (changed-artifact owners,
    # scoped knowledge, explicit contracts, conservative floors). The relation
    # walk below only adds CONTEXT (depends_on / explains / replacements): those
    # cards are read by the agent but their checkers must not run — a test suite
    # belongs to the room that owns the change, not to every neighbouring room.
    direct_ids = set(reasons)

    queue = deque(sorted(reasons))
    visited: set[str] = set()
    while queue:
        card_id = queue.popleft()
        if card_id in visited:
            continue
        visited.add(card_id)
        card = policy.card(card_id)
        for relation in policy.relations:
            if relation.source == card_id and relation.relation_type == "depends_on":
                if relation.target not in reasons:
                    queue.append(relation.target)
                select(relation.target, f"depends-on:{card_id}")
            if relation.relation_type == "explains" and relation.target == card_id:
                if relation.source not in reasons:
                    queue.append(relation.source)
                select(relation.source, f"explains:{card_id}")
            if relation.source == card_id and relation.relation_type == "replaced_by":
                if relation.target not in reasons:
                    queue.append(relation.target)
                select(relation.target, f"replacement-regression:{card_id}")
        if card.card_type == "boundary":
            for relation in policy.relations:
                if relation.source == card_id and relation.relation_type in {"producer", "consumer"}:
                    if relation.target not in reasons:
                        queue.append(relation.target)
                    select(relation.target, f"boundary-{relation.relation_type}:{card_id}")

    cards = sorted(
        (
            _card_payload(policy.card(card_id), card_reasons, freshness_by_id.get(card_id))
            for card_id, card_reasons in reasons.items()
        ),
        key=lambda card: (CARD_ORDER[card["type"]], card["id"]),
    )
    for card in cards:
        # The household gate only demands checkers from directly-hit rooms;
        # context rooms (relation walk) carry knowledge, not test obligations.
        card["direct"] = card["id"] in direct_ids
    checker_reasons: dict[str, set[str]] = defaultdict(set)
    for card_id in reasons:
        if card_id not in direct_ids:
            continue
        for checker_id in policy.card(card_id).checkers:
            checker_reasons[checker_id].add(f"selected-card:{card_id}")
    for checker in policy.checkers:
        if checker.always:
            checker_reasons[checker.checker_id].add("always")
    check_plan = [
        {
            "id": checker.checker_id,
            "stage": checker.stage,
            "target": checker.target_id,
            "command": list(checker.command),
            "selection_reasons": sorted(checker_reasons[checker.checker_id]),
        }
        for checker in sorted(policy.checkers, key=lambda item: (item.stage, item.checker_id))
        if checker.checker_id in checker_reasons
    ]
    route = {
        "state": "conservative" if fallback_reasons else "precise",
        "fallback_reasons": sorted(set(fallback_reasons)),
        "fallback_targets": sorted(fallback_targets),
    }
    payload: dict[str, Any] = {
        "schema": SLICE_SCHEMA,
        "project": manifest.project_id,
        "goal": goal.strip(),
        "entries": {"paths": artifacts, "contracts": contracts},
        "route": route,
        "cards": cards,
        "check_plan": check_plan,
        "knowledge": [
            freshness_by_id[card_id]
            for card_id in sorted(freshness_by_id)
            if card_id in reasons
        ],
        "manifest_digest": digest_file(manifest.path),
        "policy_digest": digest_file(policy.path),
        "index_facts_digest": index_summary(index)["facts_digest"],
    }
    payload["slice_digest"] = digest_json(payload)
    return payload
