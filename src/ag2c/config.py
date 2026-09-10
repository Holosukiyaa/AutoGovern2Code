from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .errors import ConfigurationError, STALE_EXTERNAL_STORE
from .households import coerce_jurisdiction
from .model import Card, Checker, ContractBinding, Coverage, Manifest, Policy, RegulatorConfig, Relation, Scope, Target
from .storage import configured_manifest, resolve_enrollment_binding
from .util import relative_config_path

MANIFEST_SCHEMA = "ag2c.manifest.v1"
POLICY_SCHEMA = "ag2c.policy.v1"
IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
CARD_TYPES = {"constitution", "floor", "boundary", "knowledge", "scenario", "task"}
OWNERSHIP_TYPES = {"primary", "reference", "supporting"}
CHECK_STAGES = {"static", "floor", "boundary", "scenario"}
CHECK_PARSE_MODES = {"", "unittest"}
RELATION_TYPES = {"depends_on", "explains", "producer", "consumer", "governs", "related_to", "replaced_by"}
COVERAGE_LEVELS = {"baseline", "structured"}


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


def _provides(value: Any, label: str) -> tuple[str, ...]:
    """Like _strings but without path normalization — provides entries are prose capability descriptions."""
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ConfigurationError(f"{label} must be a list of non-empty strings")
    return tuple(item.strip() for item in value)


def discover_manifest(start: Path | None = None, explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit.resolve()
    current = (start or Path.cwd()).resolve()
    external = configured_manifest(current)
    if external is not None:
        if external.is_file():
            return external
        binding = resolve_enrollment_binding(current)
        found = binding.get("manifest")
        if found and Path(str(found)).is_file():
            return Path(str(found)).resolve()
        raise ConfigurationError(
            f"{STALE_EXTERNAL_STORE}: configured AG2C store is missing on this computer: {external}. "
            "Add the project again or run `ag2c doctor --repair`. "
            "History is recovered only if the old external store was copied here.",
            code=STALE_EXTERNAL_STORE,
        )
    for directory in (current, *current.parents):
        candidate = directory / ".ag2c" / "manifest.json"
        if candidate.is_file():
            return candidate
    raise ConfigurationError(
        "this Git project is not managed by AG2C; add it from the AutoGovern2Code tray app or pass --manifest"
    )


def load_manifest(path: Path, *, project_root: Path | None = None) -> Manifest:
    path = path.resolve()
    raw = _load_json(path)
    if raw.get("schema") != MANIFEST_SCHEMA:
        raise ConfigurationError(f"manifest schema must be {MANIFEST_SCHEMA}")
    project = raw.get("project")
    if not isinstance(project, dict):
        raise ConfigurationError("manifest.project must be an object")
    project_id = _identifier(project.get("id", ""), "project.id")
    configured_root = project.get("root")
    if project_root is not None:
        resolved_project_root = project_root.resolve()
    elif configured_root is not None:
        candidate = Path(str(configured_root)).expanduser()
        resolved_project_root = candidate.resolve() if candidate.is_absolute() else (path.parent / candidate).resolve()
    else:
        resolved_project_root = path.parent.parent.resolve()
    external = configured_root is not None
    config_root = path.parent if external else resolved_project_root
    policy_default = "policy.json" if external else ".ag2c/policy.json"
    state_default = "state" if external else ".ag2c/state"
    ledger_default = "ledger.jsonl" if external else ".ag2c/ledger.jsonl"
    policy_rel = relative_config_path(str(raw.get("policy", policy_default)), "manifest.policy")
    state_rel = relative_config_path(str(raw.get("state_dir", state_default)), "manifest.state_dir")
    ledger_rel = relative_config_path(str(raw.get("ledger", ledger_default)), "manifest.ledger")
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
        project_root=resolved_project_root,
        project_id=project_id,
        policy_path=(config_root / policy_rel).resolve(),
        state_dir=(config_root / state_rel).resolve(),
        ledger_path=(config_root / ledger_rel).resolve(),
        targets=tuple(targets),
        trunk=str(project.get("trunk") or "").strip(),
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
                jurisdiction=coerce_jurisdiction(item.get("jurisdiction")),
                provides=_provides(item.get("provides"), f"card {card_id} provides"),
                conventions=str(item.get("conventions", "") or "").strip(),
                budget_lines=max(0, int(item.get("budget_lines", 0) or 0)),
                budget_chars=max(0, int(item.get("budget_chars", 0) or 0)),
                budget_ast_nodes=max(0, int(item.get("budget_ast_nodes", 0) or 0)),
                optional=bool(item.get("optional", False)),
                maturity=str(item.get("maturity", "") or "").strip(),
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
        if (card.card_type == "task" or (card.card_type == "knowledge" and card.jurisdiction is None)) and card.checkers:
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
            "replaced_by": ("knowledge", "knowledge"),
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
        always = item.get("always", False)
        if not isinstance(always, bool):
            raise ConfigurationError(f"checker {checker_id} always must be a boolean")
        parse = str(item.get("parse") or "").strip()
        if parse not in CHECK_PARSE_MODES:
            raise ConfigurationError(f"checker {checker_id} has unsupported parse mode: {parse}")
        try:
            budget_seconds = float(item.get("budget_seconds", 0) or 0)
        except (TypeError, ValueError):
            raise ConfigurationError(f"checker {checker_id} budget_seconds must be a number")
        if budget_seconds < 0:
            raise ConfigurationError(f"checker {checker_id} budget_seconds must be non-negative")
        checkers.append(Checker(checker_id, stage, target_id, command, cwd, timeout, str(item.get("implementation") or ""), always, parse, budget_seconds))
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
    raw_coverage = raw.get("coverage", {})
    if not isinstance(raw_coverage, dict):
        raise ConfigurationError("policy.coverage must be an object")
    inferred_level = "structured" if len([card for card in cards if card.card_type == "floor"]) > 1 or contracts else "baseline"
    coverage_level = str(raw_coverage.get("level", inferred_level)).strip()
    if coverage_level not in COVERAGE_LEVELS:
        raise ConfigurationError(f"policy.coverage.level must be one of: {', '.join(sorted(COVERAGE_LEVELS))}")
    coverage_strategy = str(raw_coverage.get("strategy", "conservative")).strip()
    if coverage_strategy != "conservative":
        raise ConfigurationError("policy.coverage.strategy must be conservative")
    coverage = Coverage(
        level=coverage_level,
        strategy=coverage_strategy,
        managed_by=str(raw_coverage.get("managed_by", "project")).strip() or "project",
        areas=_strings(raw_coverage.get("areas"), "policy.coverage.areas"),
    )
    from .households import validate_declarations

    validate_declarations(cards, relations)
    household_required = raw.get("household_required", False)
    if not isinstance(household_required, bool):
        raise ConfigurationError("household_required must be a boolean")
    regulator = _regulator_config(raw.get("regulator"))
    checker_parallelism = raw.get("checker_parallelism", 1)
    if not isinstance(checker_parallelism, int) or isinstance(checker_parallelism, bool) or checker_parallelism < 1:
        raise ConfigurationError("checker_parallelism must be a positive integer")
    return Policy(manifest.policy_path, tuple(cards), tuple(relations), tuple(contracts), tuple(checkers), coverage, household_required, regulator, checker_parallelism)


def _regulator_config(value: Any) -> RegulatorConfig | None:
    """Parse policy.regulator — the AI reviewer called after machine checks pass.

    Absent key means no regulator configured (verify degrades with a recorded
    gap). An present object is validated strictly: enabled requires endpoint
    and model; strict (default true) turns regulator-unavailable into a merge
    block — the regulator is the only semantic check layer, so a configured
    but absent regulator fails closed unless the user explicitly opts out
    with ``govern regulator --strict off``.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ConfigurationError("policy.regulator must be an object")
    enabled = value.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ConfigurationError("policy.regulator.enabled must be a boolean")
    strict = value.get("strict", True)
    if not isinstance(strict, bool):
        raise ConfigurationError("policy.regulator.strict must be a boolean")
    endpoint = str(value.get("endpoint", "") or "").strip()
    model = str(value.get("model", "") or "").strip()
    api_key_env = str(value.get("api_key_env", "") or "").strip() or "AG2C_REGULATOR_API_KEY"
    timeout = int(value.get("timeout", 180) or 180)
    if timeout < 1:
        raise ConfigurationError("policy.regulator.timeout must be positive")
    if enabled and (not endpoint or not model):
        raise ConfigurationError("policy.regulator requires endpoint and model when enabled")
    return RegulatorConfig(
        enabled=enabled,
        endpoint=endpoint,
        model=model,
        api_key_env=api_key_env,
        strict=strict,
        timeout=timeout,
        worker_model=str(value.get("worker_model", "") or "").strip(),
        allow_same_family=bool(value.get("allow_same_family", False)),
    )
