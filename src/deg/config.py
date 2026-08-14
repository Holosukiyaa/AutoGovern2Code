from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .errors import ConfigurationError
from .model import Card, Checker, ContractBinding, Manifest, Policy, Relation, Scope, Target
from .util import relative_config_path

MANIFEST_SCHEMA = "deg.manifest.v1"
POLICY_SCHEMA = "deg.policy.v1"
IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
CARD_TYPES = {"constitution", "floor", "boundary", "knowledge", "scenario", "task"}
OWNERSHIP_TYPES = {"primary", "reference", "supporting"}
CHECK_STAGES = {"static", "floor", "boundary", "scenario"}
RELATION_TYPES = {"depends_on", "explains", "producer", "consumer", "governs", "related_to"}


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigurationError(f"configuration file does not exist: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"cannot read JSON configuration {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigurationError(f"configuration root must be an object: {path}")
    return value


def _identifier(value: Any, label: str) -> str:
    result = str(value).strip()
    if not IDENTIFIER.fullmatch(result):
        raise ConfigurationError(f"{label} must match {IDENTIFIER.pattern}: {result!r}")
    return result


def _strings(value: Any, label: str, *, required: bool = False) -> tuple[str, ...]:
    if value is None:
        value = []
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ConfigurationError(f"{label} must be a list of non-empty strings")
    result = tuple(item.replace("\\", "/").strip() for item in value)
    if required and not result:
        raise ConfigurationError(f"{label} must not be empty")
    return result


def discover_manifest(start: Path | None = None, explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit.resolve()
    current = (start or Path.cwd()).resolve()
    for directory in (current, *current.parents):
        candidate = directory / ".deg" / "manifest.json"
        if candidate.is_file():
            return candidate
    raise ConfigurationError(
        "cannot find .deg/manifest.json; enroll the project with $deg-governed-development or pass --manifest"
    )


def load_manifest(path: Path) -> Manifest:
    path = path.resolve()
    raw = _load_json(path)
    if raw.get("schema") != MANIFEST_SCHEMA:
        raise ConfigurationError(f"manifest schema must be {MANIFEST_SCHEMA}")
    project = raw.get("project")
    if not isinstance(project, dict):
        raise ConfigurationError("manifest.project must be an object")
    project_id = _identifier(project.get("id", ""), "project.id")
    project_root = path.parent.parent.resolve()
    policy_rel = relative_config_path(str(raw.get("policy", ".deg/policy.json")), "manifest.policy")
    state_rel = relative_config_path(str(raw.get("state_dir", ".deg/state")), "manifest.state_dir")
    ledger_rel = relative_config_path(str(raw.get("ledger", ".deg/ledger.jsonl")), "manifest.ledger")
    raw_targets = raw.get("targets")
    if not isinstance(raw_targets, list) or not raw_targets:
        raise ConfigurationError("manifest.targets must be a non-empty list")
    targets: list[Target] = []
    for index, item in enumerate(raw_targets):
        if not isinstance(item, dict):
            raise ConfigurationError(f"manifest.targets[{index}] must be an object")
        target_id = _identifier(item.get("id", ""), f"manifest.targets[{index}].id")
        target_path = str(item.get("path", ".")).strip() or "."
        roots = _strings(item.get("governed_roots"), f"target {target_id} governed_roots", required=True)
        excludes = _strings(item.get("exclude"), f"target {target_id} exclude")
        targets.append(Target(target_id, target_path, roots, excludes))
    ids = [target.target_id for target in targets]
    if len(ids) != len(set(ids)):
        raise ConfigurationError("manifest target ids must be unique")
    return Manifest(
        path=path,
        project_root=project_root,
        project_id=project_id,
        policy_path=(project_root / policy_rel).resolve(),
        state_dir=(project_root / state_rel).resolve(),
        ledger_path=(project_root / ledger_rel).resolve(),
        targets=tuple(targets),
    )


def load_policy(manifest: Manifest) -> Policy:
    raw = _load_json(manifest.policy_path)
    if raw.get("schema") != POLICY_SCHEMA:
        raise ConfigurationError(f"policy schema must be {POLICY_SCHEMA}")
    target_ids = {target.target_id for target in manifest.targets}
    cards: list[Card] = []
    for index, item in enumerate(raw.get("cards", [])):
        if not isinstance(item, dict):
            raise ConfigurationError(f"policy.cards[{index}] must be an object")
        card_id = _identifier(item.get("id", ""), f"policy.cards[{index}].id")
        card_type = str(item.get("type", "")).strip()
        if card_type not in CARD_TYPES:
            raise ConfigurationError(f"card {card_id} has unsupported type: {card_type}")
        title = str(item.get("title", "")).strip()
        summary = str(item.get("summary", "")).strip()
        if not title or not summary:
            raise ConfigurationError(f"card {card_id} requires title and summary")
        scopes: list[Scope] = []
        for scope_index, scope in enumerate(item.get("scopes", [])):
            if not isinstance(scope, dict):
                raise ConfigurationError(f"card {card_id} scope {scope_index} must be an object")
            target_id = _identifier(scope.get("target", ""), f"card {card_id} scope target")
            if target_id not in target_ids:
                raise ConfigurationError(f"card {card_id} references unknown target: {target_id}")
            ownership = str(scope.get("ownership", "reference")).strip()
            if ownership not in OWNERSHIP_TYPES:
                raise ConfigurationError(f"card {card_id} scope has invalid ownership: {ownership}")
            if ownership == "primary" and card_type != "floor":
                raise ConfigurationError(f"only floor cards can own primary scopes: {card_id}")
            scopes.append(
                Scope(
                    target_id=target_id,
                    includes=_strings(scope.get("include"), f"card {card_id} scope include", required=True),
                    excludes=_strings(scope.get("exclude"), f"card {card_id} scope exclude"),
                    ownership=ownership,
                )
            )
        cards.append(
            Card(
                card_id=card_id,
                card_type=card_type,
                title=title,
                summary=summary,
                scopes=tuple(scopes),
                checkers=_strings(item.get("checkers"), f"card {card_id} checkers"),
                references=_strings(item.get("references"), f"card {card_id} references"),
            )
        )
    card_ids = [card.card_id for card in cards]
    if len(card_ids) != len(set(card_ids)):
        raise ConfigurationError("policy card ids must be unique")
    known_cards = set(card_ids)
    cards_by_id = {card.card_id: card for card in cards}
    for card in cards:
        if card.card_type == "floor" and not any(scope.ownership == "primary" for scope in card.scopes):
            raise ConfigurationError(f"floor card requires at least one primary scope: {card.card_id}")
        if card.card_type == "floor" and not card.checkers:
            raise ConfigurationError(f"floor card requires at least one floor checker: {card.card_id}")
        if card.card_type in {"knowledge", "task"} and card.checkers:
            raise ConfigurationError(f"{card.card_type} card cannot own checkers: {card.card_id}")
    relations: list[Relation] = []
    for index, item in enumerate(raw.get("relations", [])):
        if not isinstance(item, dict):
            raise ConfigurationError(f"policy.relations[{index}] must be an object")
        source = _identifier(item.get("source", ""), f"relation {index} source")
        target = _identifier(item.get("target", ""), f"relation {index} target")
        relation_type = str(item.get("type", "")).strip()
        if source not in known_cards or target not in known_cards:
            raise ConfigurationError(f"relation {source} -> {target} references an unknown card")
        if relation_type not in RELATION_TYPES:
            raise ConfigurationError(f"relation {source} -> {target} has unsupported type: {relation_type}")
        source_type = cards_by_id[source].card_type
        target_type = cards_by_id[target].card_type
        expected_types = {
            "depends_on": ("floor", "floor"),
            "explains": ("knowledge", "floor"),
            "producer": ("boundary", "floor"),
            "consumer": ("boundary", "floor"),
        }
        if relation_type in expected_types and (source_type, target_type) != expected_types[relation_type]:
            expected_source, expected_target = expected_types[relation_type]
            raise ConfigurationError(
                f"{relation_type} relation requires {expected_source} -> {expected_target}: {source} -> {target}"
            )
        if relation_type == "governs" and source_type != "constitution":
            raise ConfigurationError(f"governs relation requires a constitution source: {source}")
        relations.append(Relation(source, relation_type, target))
    checkers: list[Checker] = []
    for index, item in enumerate(raw.get("checkers", [])):
        if not isinstance(item, dict):
            raise ConfigurationError(f"policy.checkers[{index}] must be an object")
        checker_id = _identifier(item.get("id", ""), f"policy.checkers[{index}].id")
        stage = str(item.get("stage", "")).strip()
        if stage not in CHECK_STAGES:
            raise ConfigurationError(f"checker {checker_id} has unsupported stage: {stage}")
        target_value = item.get("target")
        target_id = _identifier(target_value, f"checker {checker_id} target") if target_value is not None else None
        if target_id is not None and target_id not in target_ids:
            raise ConfigurationError(f"checker {checker_id} references unknown target: {target_id}")
        command = _strings(item.get("command"), f"checker {checker_id} command", required=True)
        timeout = int(item.get("timeout", 300))
        if timeout < 1:
            raise ConfigurationError(f"checker {checker_id} timeout must be positive")
        cwd = relative_config_path(str(item.get("cwd", ".")), f"checker {checker_id} cwd")
        checkers.append(Checker(checker_id, stage, target_id, command, cwd, timeout))
    checker_ids = [checker.checker_id for checker in checkers]
    if len(checker_ids) != len(set(checker_ids)):
        raise ConfigurationError("policy checker ids must be unique")
    known_checkers = set(checker_ids)
    for card in cards:
        unknown = sorted(set(card.checkers) - known_checkers)
        if unknown:
            raise ConfigurationError(f"card {card.card_id} references unknown checkers: {', '.join(unknown)}")
        expected_stage = {
            "constitution": "static",
            "floor": "floor",
            "boundary": "boundary",
            "scenario": "scenario",
        }.get(card.card_type)
        invalid = [
            checker_id for checker_id in card.checkers
            if expected_stage is not None and next(item for item in checkers if item.checker_id == checker_id).stage != expected_stage
        ]
        if invalid:
            raise ConfigurationError(
                f"card {card.card_id} can only bind {expected_stage} checkers: {', '.join(sorted(invalid))}"
            )
    bound_checkers = {checker_id for card in cards for checker_id in card.checkers}
    orphaned = sorted(known_checkers - bound_checkers)
    if orphaned:
        raise ConfigurationError("every checker must be bound to a card: " + ", ".join(orphaned))
    contracts: list[ContractBinding] = []
    for index, item in enumerate(raw.get("contracts", [])):
        if not isinstance(item, dict):
            raise ConfigurationError(f"policy.contracts[{index}] must be an object")
        target_id = _identifier(item.get("target", ""), f"contract {index} target")
        contract_id = _identifier(item.get("id", ""), f"contract {index} id")
        version = str(item.get("version", "")).strip()
        boundary = _identifier(item.get("boundary", ""), f"contract {index} boundary")
        scenarios = _strings(item.get("scenarios"), f"contract {contract_id} scenarios", required=True)
        if target_id not in target_ids or boundary not in known_cards or any(item not in known_cards for item in scenarios):
            raise ConfigurationError(f"contract binding {target_id}:{contract_id}@{version} has unknown references")
        if cards_by_id[boundary].card_type != "boundary":
            raise ConfigurationError(f"contract {target_id}:{contract_id}@{version} must bind a boundary card")
        if any(cards_by_id[scenario].card_type != "scenario" for scenario in scenarios):
            raise ConfigurationError(f"contract {target_id}:{contract_id}@{version} scenarios must be scenario cards")
        boundary_relations = [relation for relation in relations if relation.source == boundary]
        relation_types = {relation.relation_type for relation in boundary_relations}
        if not {"producer", "consumer"}.issubset(relation_types):
            raise ConfigurationError(
                f"contract boundary requires producer and consumer relations: {target_id}:{contract_id}@{version}"
            )
        if not cards_by_id[boundary].checkers:
            raise ConfigurationError(f"contract boundary requires a boundary checker: {boundary}")
        missing_scenario_checks = [scenario for scenario in scenarios if not cards_by_id[scenario].checkers]
        if missing_scenario_checks:
            raise ConfigurationError(
                "contract scenarios require scenario checkers: " + ", ".join(missing_scenario_checks)
            )
        if not version:
            raise ConfigurationError(f"contract {target_id}:{contract_id} requires a version")
        contracts.append(ContractBinding(target_id, contract_id, version, boundary, scenarios))
    contract_keys = [contract.key for contract in contracts]
    if len(contract_keys) != len(set(contract_keys)):
        raise ConfigurationError("policy contract binding keys must be unique")
    if not any(card.card_type == "floor" for card in cards):
        raise ConfigurationError("policy requires at least one floor card")
    return Policy(manifest.policy_path, tuple(cards), tuple(relations), tuple(contracts), tuple(checkers))
