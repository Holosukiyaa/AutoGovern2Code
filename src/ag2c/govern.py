from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import discover_manifest, load_manifest, load_policy
from .errors import AG2CError, ConfigurationError
from .gitops import repository_root
from .index import build_index, index_path
from .knowledge import knowledge_status, sync_knowledge
from .ledger import append_event
from .model import Manifest
from .slicer import compile_slice
from .util import normalize_artifact_path


PENDING_FILENAME = "governance-pending.json"
PENDING_TITLES = {
    "unowned-area": "新目录还没有登记",
    "new-document": "新文档还没有入库",
    "changed-document": "文档有变化，需要更新 Knowledge",
    "stale-knowledge": "Knowledge 已过期",
    "assertion-conflict": "文档要点和记录冲突",
    "new-interface": "检测到新的公开界面",
    "undeclared-product": "还没有产品验收",
}
PENDING_HINTS = {
    "add-or-expand-floor": "补目录归属",
    "add-knowledge": "加入 Knowledge",
    "add-or-update-knowledge": "更新 Knowledge",
    "sync-or-update-knowledge": "同步 Knowledge",
    "review-then-sync-knowledge": "核对要点后再同步",
    "add-boundary": "登记公开界面，并补上对应检查",
    "declare-product-checks": "补上要验的能力和对应检查",
}
DOC_NAMES = ("README.md", "README.zh-CN.md", "README.en.md", "CONTRIBUTING.md", "CHANGELOG.md", "AGENTS.md")
DOC_DIRS = ("docs", "doc", "handbook")
BOUNDARY_HINTS = {"api", "routes", "graphql", "proto", "openapi", "handlers", "endpoints"}
SKIP_DIRS = {".git", "node_modules", "dist", "build", ".next", "__pycache__", ".venv", "venv"}
MAX_KNOWLEDGE_CARDS = 30


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AG2CError(f"cannot read governance file {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AG2CError(f"governance file must contain an object: {path}")
    return value


def _slug(value: str) -> str:
    from .enrollment import _area_slug

    return _area_slug(value.replace("\\", "/").replace("/", "-").replace(".", "-"))


def _first_line(path: Path) -> str:
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            text = line.strip().lstrip("#").strip()
            if text:
                return text[:180]
    except OSError:
        pass
    return path.name


def _floor_for_path(cards: list[dict[str, Any]], relative: str) -> str | None:
    normalized = relative.replace("\\", "/").lstrip("./")
    best_id = None
    best_len = -1
    for card in cards:
        if card.get("type") != "floor":
            continue
        for scope in card.get("scopes") or []:
            for pattern in scope.get("include") or []:
                prefix = str(pattern).replace("\\", "/").replace("/**", "").rstrip("*").rstrip("/")
                if pattern == "**" or normalized == prefix or normalized.startswith(prefix + "/") or prefix in {"", "."}:
                    if len(prefix) > best_len:
                        best_id = str(card["id"])
                        best_len = len(prefix)
    if best_id:
        return best_id
    floors = [str(card["id"]) for card in cards if card.get("type") == "floor"]
    return floors[0] if floors else None


def _skip_part(name: str) -> bool:
    return name in SKIP_DIRS or name.startswith(".")


def _document_paths(root: Path) -> list[str]:
    found: list[str] = []
    for path in sorted(root.glob("*.md")):
        found.append(path.name)
    for name in DOC_NAMES:
        if name not in found and (root / name).is_file():
            found.append(name)
    for folder in DOC_DIRS:
        directory = root / folder
        if not directory.is_dir() or _skip_part(folder):
            continue
        for path in sorted(directory.rglob("*.md")):
            if any(_skip_part(part) for part in path.relative_to(root).parts):
                continue
            found.append(path.relative_to(root).as_posix())
            if len(found) >= MAX_KNOWLEDGE_CARDS:
                return found
    return found


def _boundary_paths(root: Path) -> list[str]:
    found: list[str] = []
    for dirpath, dirnames, _filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if not _skip_part(name)]
        current = Path(dirpath)
        if current == root or current.name.lower() not in BOUNDARY_HINTS:
            continue
        found.append(current.relative_to(root).as_posix())
        if len(found) >= 12:
            break
    for name in ("openapi.yaml", "openapi.yml", "swagger.yaml", "swagger.json"):
        if (root / name).is_file() and name not in found:
            found.append(name)
    return found


def compose_baseline_governance(root: Path, project_roots: list[str], checker_ids: list[str]) -> dict[str, Any]:
    from .enrollment import _baseline_cards

    cards = list(_baseline_cards(root, project_roots, checker_ids))
    relations: list[dict[str, str]] = []
    constitution = next((card["id"] for card in cards if card.get("type") == "constitution"), None)
    for card in cards:
        if constitution and card.get("type") == "floor":
            relations.append({"source": constitution, "type": "governs", "target": card["id"]})
    used = {str(card["id"]) for card in cards}
    for relative in _document_paths(root):
        card_id = f"knowledge.{_slug(relative)}"
        if card_id in used:
            continue
        used.add(card_id)
        title = Path(relative).name
        cards.append(
            {
                "id": card_id,
                "type": "knowledge",
                "title": title,
                "summary": _first_line(root / relative) or f"Project knowledge from {relative}",
                "scopes": [{"target": "app", "include": [relative], "ownership": "reference"}],
                "references": [relative],
            }
        )
        floors = [str(card["id"]) for card in cards if card.get("type") == "floor"]
        if Path(relative).parent.as_posix() in {".", ""}:
            for floor_id in floors:
                relations.append({"source": card_id, "type": "explains", "target": floor_id})
        else:
            floor_id = _floor_for_path(cards, relative)
            if floor_id:
                relations.append({"source": card_id, "type": "explains", "target": floor_id})
    for relative in _boundary_paths(root):
        card_id = f"boundary.{_slug(relative)}"
        if card_id in used:
            continue
        used.add(card_id)
        include = [relative] if (root / relative).is_file() else [f"{relative}/**"]
        cards.append(
            {
                "id": card_id,
                "type": "boundary",
                "title": f"{Path(relative).name} interface",
                "summary": f"Detected public surface at {relative}.",
                "scopes": [{"target": "app", "include": include, "ownership": "reference"}],
                "references": include,
            }
        )
        floor_id = _floor_for_path(cards, relative)
        if floor_id:
            relations.append({"source": card_id, "type": "related_to", "target": floor_id})
    return {"cards": cards, "relations": relations, "contracts": []}


def finalize_ingest(manifest: Manifest, *, actor: str, reason: str) -> dict[str, Any]:
    policy = load_policy(manifest)
    knowledge_ids = [card.card_id for card in policy.cards if card.card_type == "knowledge" and card.references]
    synced = None
    if knowledge_ids:
        synced = sync_knowledge(manifest, policy, card_ids=knowledge_ids, actor=actor, reason=reason)
    build_index(manifest, policy, index_path(manifest))
    event = append_event(
        manifest.ledger_path,
        "governance-ingested",
        {
            "actor": actor,
            "reason": reason,
            "knowledge": knowledge_ids,
            "floors": [card.card_id for card in policy.cards if card.card_type == "floor"],
            "boundaries": [card.card_id for card in policy.cards if card.card_type == "boundary"],
        },
    )
    pending_updates(manifest.project_root)
    return {
        "knowledge": knowledge_ids,
        "synced": None if synced is None else synced["cards"],
        "floors": [card.card_id for card in policy.cards if card.card_type == "floor"],
        "boundaries": [card.card_id for card in policy.cards if card.card_type == "boundary"],
        "relations": len(policy.relations),
        "ledger_event_digest": event["event_digest"],
    }


def ingest_project(start: Path, *, actor: str, reason: str) -> dict[str, Any]:
    actor = actor.strip()
    reason = reason.strip()
    if not actor:
        raise AG2CError("governance ingest requires --actor")
    if not reason:
        raise AG2CError("governance ingest requires --reason")
    root = repository_root(start)
    manifest = load_manifest(discover_manifest(root), project_root=root)
    raw = _read_json(manifest.policy_path)
    from .enrollment import _native_checkers, _tracked_roots

    project_roots = _tracked_roots(root)
    checkers = raw.get("checkers") or _native_checkers(root)
    checker_ids = [str(item["id"]) for item in checkers if isinstance(item, dict)]
    coverage = raw.get("coverage") if isinstance(raw.get("coverage"), dict) else {}
    generated = coverage.get("managed_by") == "ag2c" and coverage.get("level") == "baseline"
    composed = compose_baseline_governance(root, project_roots, checker_ids)
    if generated:
        raw["cards"] = composed["cards"]
        raw["relations"] = composed["relations"]
        raw["contracts"] = raw.get("contracts") or []
        raw["coverage"] = {
            "level": "baseline",
            "strategy": "conservative",
            "managed_by": "ag2c",
            "areas": project_roots,
        }
    else:
        existing = {str(card.get("id")) for card in raw.get("cards", []) if isinstance(card, dict)}
        for card in composed["cards"]:
            if card["id"] not in existing and card["type"] in {"knowledge", "boundary"}:
                raw.setdefault("cards", []).append(card)
                existing.add(card["id"])
        known = {str(item.get("source")) + ":" + str(item.get("type")) + ":" + str(item.get("target")) for item in raw.get("relations", [])}
        for relation in composed["relations"]:
            key = f"{relation['source']}:{relation['type']}:{relation['target']}"
            if key not in known:
                raw.setdefault("relations", []).append(relation)
    _atomic_json(manifest.policy_path, raw)
    try:
        load_policy(manifest)
    except ConfigurationError as exc:
        raise AG2CError(f"ingested policy is invalid: {exc}") from exc
    result = finalize_ingest(manifest, actor=actor, reason=reason)
    result["generated"] = generated
    result["reason"] = reason
    result["actor"] = actor
    return result


def pending_updates(start: Path, changed_paths: list[str] | None = None) -> dict[str, Any]:
    root = repository_root(start)
    manifest = load_manifest(discover_manifest(root), project_root=root)
    policy = load_policy(manifest)
    from .enrollment import _tracked_roots

    items: list[dict[str, str]] = []
    owned: set[str] = set()
    for card in policy.cards:
        if card.card_type != "floor":
            continue
        for scope in card.scopes:
            for pattern in scope.includes:
                owned.add(pattern.replace("/**", "").rstrip("*").rstrip("/"))
    for name in _tracked_roots(root):
        if name not in owned and not any(name.startswith(prefix + "/") or prefix == name for prefix in owned if prefix):
            items.append({"kind": "unowned-area", "path": name, "action": "add-or-expand-floor"})
    referenced = {ref.replace("\\", "/") for card in policy.cards for ref in card.references}
    for relative in _document_paths(root):
        if relative not in referenced:
            items.append({"kind": "new-document", "path": relative, "action": "add-knowledge"})
    for status in knowledge_status(manifest, policy):
        if status["status"] == "conflict":
            items.append({"kind": "assertion-conflict", "path": status["id"], "action": "review-then-sync-knowledge"})
        elif status["status"] == "stale":
            items.append({"kind": "stale-knowledge", "path": status["id"], "action": "sync-or-update-knowledge"})
    for relative in changed_paths or []:
        normalized = relative.replace("\\", "/").lstrip("./")
        if normalized.endswith(".md") and normalized not in referenced:
            items.append({"kind": "changed-document", "path": normalized, "action": "add-or-update-knowledge"})
        if any(part.lower() in BOUNDARY_HINTS for part in Path(normalized).parts):
            if not any(normalized.startswith(str(scope.includes[0]).replace("/**", "")) for card in policy.cards if card.card_type == "boundary" for scope in card.scopes if scope.includes):
                items.append({"kind": "new-interface", "path": normalized, "action": "add-boundary"})
    if not policy.contracts and not any(checker.stage in {"boundary", "scenario"} for checker in policy.checkers):
        items.append({"kind": "undeclared-product", "path": ".", "action": "declare-product-checks"})
    unique: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        key = (item["kind"], item["path"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(
            {
                **item,
                "title": PENDING_TITLES.get(item["kind"], item["kind"]),
                "hint": PENDING_HINTS.get(item["action"], item["action"]),
            }
        )
    stored = {"updated_at": _now(), "items": unique}
    _atomic_json(manifest.state_dir / PENDING_FILENAME, stored)
    return stored


def stored_pending(start: Path) -> dict[str, Any]:
    try:
        root = repository_root(start)
        manifest = load_manifest(discover_manifest(root), project_root=root)
    except AG2CError:
        return {"items": []}
    path = manifest.state_dir / PENDING_FILENAME
    if not path.is_file():
        return {"items": []}
    try:
        value = _read_json(path)
    except AG2CError:
        return {"items": []}
    return value if isinstance(value.get("items"), list) else {"items": []}


def settle_pending(start: Path, *, actor: str, reason: str) -> dict[str, Any]:
    actor = actor.strip()
    reason = reason.strip()
    if not actor or not reason:
        raise AG2CError("governance settle requires --actor and --reason")
    pending = pending_updates(start)
    items = list(pending.get("items") or [])
    actions: list[str] = []
    kinds = {str(item.get("kind")) for item in items}
    if kinds & {"unowned-area", "new-document", "changed-document", "new-interface"}:
        ingest_project(start, actor=actor, reason=reason)
        actions.append("ingest")
    stale_ids = [str(item["path"]) for item in items if item.get("kind") == "stale-knowledge"]
    if stale_ids:
        root = repository_root(start)
        manifest = load_manifest(discover_manifest(root), project_root=root)
        policy = load_policy(manifest)
        sync_knowledge(manifest, policy, card_ids=stale_ids, actor=actor, reason=reason)
        actions.append("sync")
    # Assertion conflicts stay pending until an explicit knowledge sync after review.
    remaining = pending_updates(start)
    event = append_event(
        load_manifest(discover_manifest(repository_root(start))).ledger_path,
        "governance-settled",
        {"actor": actor, "reason": reason, "actions": actions, "settled": len(items), "remaining": len(remaining.get("items") or [])},
    )
    return {
        "actor": actor,
        "reason": reason,
        "actions": actions,
        "settled": items,
        "pending": remaining.get("items") or [],
        "ledger_event_digest": event["event_digest"],
    }


def apply_change(
    start: Path,
    *,
    action: str,
    kind: str,
    card_id: str,
    reason: str,
    actor: str,
    card_type: str = "knowledge",
    title: str = "",
    summary: str = "",
    include: list[str] | None = None,
) -> dict[str, Any]:
    actor = actor.strip()
    reason = reason.strip()
    card_id = card_id.strip()
    if not actor or not reason or not card_id:
        raise AG2CError("governance apply requires --actor, --reason, and --id")
    if action not in {"add", "update", "remove"}:
        raise AG2CError("governance action must be add, update, or remove")
    if kind != "card":
        raise AG2CError("this release applies card changes; add a boundary or Knowledge card to record a protocol")
    root = repository_root(start)
    manifest = load_manifest(discover_manifest(root), project_root=root)
    raw = _read_json(manifest.policy_path)
    cards = [item for item in raw.get("cards", []) if isinstance(item, dict)]
    existing = {str(item.get("id")): item for item in cards}
    if action == "remove":
        if card_id not in existing:
            raise AG2CError(f"unknown card: {card_id}")
        if existing[card_id].get("type") == "constitution":
            raise AG2CError("refusing to remove the constitution card")
        if existing[card_id].get("type") == "floor" and sum(1 for item in cards if item.get("type") == "floor") <= 1:
            raise AG2CError("refusing to remove the last floor card")
        raw["cards"] = [item for item in cards if item.get("id") != card_id]
        raw["relations"] = [
            item
            for item in raw.get("relations", [])
            if isinstance(item, dict) and item.get("source") != card_id and item.get("target") != card_id
        ]
    else:
        includes = [normalize_artifact_path(item) for item in (include or existing.get(card_id, {}).get("scopes", [{}])[0].get("include") or [])]
        if action == "add" and card_id in existing:
            raise AG2CError(f"card already exists: {card_id}")
        if action == "update" and card_id not in existing:
            raise AG2CError(f"unknown card: {card_id}")
        if action == "add" and card_type not in {"knowledge", "boundary", "floor"}:
            raise AG2CError("new cards must be knowledge, boundary, or floor")
        current = dict(existing.get(card_id) or {})
        current["id"] = card_id
        current["type"] = card_type if action == "add" else current.get("type") or card_type
        current["title"] = title.strip() or current.get("title") or card_id
        current["summary"] = summary.strip() or current.get("summary") or reason
        if not includes:
            raise AG2CError("card apply requires --include")
        current["scopes"] = [{"target": "app", "include": includes, "ownership": "primary" if current["type"] == "floor" else "reference"}]
        if current["type"] == "floor":
            checker_ids = [str(item["id"]) for item in raw.get("checkers", []) if isinstance(item, dict)]
            if not checker_ids:
                raise AG2CError("floor cards require an existing checker")
            current["checkers"] = current.get("checkers") or [checker_ids[0]]
        else:
            current.pop("checkers", None)
        if current["type"] == "knowledge":
            current["references"] = includes
        if action == "add":
            cards.append(current)
            raw["cards"] = cards
            floor_id = _floor_for_path(cards, includes[0])
            if floor_id and current["type"] == "knowledge":
                raw.setdefault("relations", []).append({"source": card_id, "type": "explains", "target": floor_id})
        else:
            raw["cards"] = [current if item.get("id") == card_id else item for item in cards]
    _atomic_json(manifest.policy_path, raw)
    try:
        policy = load_policy(manifest)
    except ConfigurationError as exc:
        raise AG2CError(f"updated policy is invalid: {exc}") from exc
    build_index(manifest, policy, index_path(manifest))
    remaining = next((card for card in policy.cards if card.card_id == card_id), None)
    if remaining is not None and remaining.card_type == "knowledge" and remaining.references:
        sync_knowledge(manifest, policy, card_ids=[card_id], actor=actor, reason=reason)
    event = append_event(
        manifest.ledger_path,
        "governance-applied",
        {"action": action, "kind": kind, "id": card_id, "actor": actor, "reason": reason},
    )
    pending_updates(root)
    return {
        "action": action,
        "id": card_id,
        "actor": actor,
        "reason": reason,
        "ledger_event_digest": event["event_digest"],
    }


def retrieve_guidance(start: Path, *, path_specs: list[str], contract_specs: list[str] | None = None, goal: str = "", all_mode: bool = False) -> dict[str, Any]:
    root = repository_root(start)
    manifest = load_manifest(discover_manifest(root), project_root=root)
    policy = load_policy(manifest)
    entry = compile_slice(
        manifest,
        policy,
        path_specs=path_specs,
        contract_specs=list(contract_specs or []),
        goal=goal,
        all_mode=all_mode,
    )
    pending_path = manifest.state_dir / PENDING_FILENAME
    pending = _read_json(pending_path) if pending_path.is_file() else {"items": []}
    return {
        "route": entry["route"],
        "knowledge": entry.get("knowledge") or [],
        "cards": [
            {"id": card["id"], "type": card["type"], "title": card["title"], "summary": card["summary"]}
            for card in entry.get("cards") or []
        ],
        "pending": pending.get("items") or [],
    }


def record_pending_from_task(canonical: Path, changed_paths: list[str]) -> dict[str, Any]:
    return pending_updates(canonical, changed_paths)
