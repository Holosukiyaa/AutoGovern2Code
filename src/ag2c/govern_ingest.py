"""Extracted by flatten-split."""
from __future__ import annotations
from .govern_support import BOUNDARY_HINTS, DOC_DIRS, DOC_NAMES, MAX_KNOWLEDGE_CARDS, PENDING_FILENAME, SKIP_DIRS, _atomic_json, _first_line, _floor_for_path, _read_json, _slug
import os
from pathlib import Path
from typing import Any
from .config import discover_manifest, load_manifest, load_policy
from .errors import AG2CError, ConfigurationError
from ag2c_gui.graph import clip_knowledge_title
from .gitops import repository_root
from .ledger import append_event
from .slicer import compile_slice

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
        title = clip_knowledge_title(Path(relative).name)
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
        floor_id = (
            "floor.root"
            if Path(relative).parent.as_posix() in {".", ""} and any(card.get("id") == "floor.root" for card in cards)
            else _floor_for_path(cards, relative)
        )
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
    for name in [item for item in project_roots if (root / item).is_dir()]:
        card_id = f"knowledge.{_slug(name)}"
        if card_id in used:
            continue
        floor_id = _floor_for_path(cards, f"{name}/.")
        if not floor_id:
            continue
        used.add(card_id)
        slug = _slug(name)
        cards.append(
            {
                "id": card_id,
                "type": "knowledge",
                "title": f"{name} exploring household",
                "summary": f"Declared exploring household for the top-level {name} directory. Meaning is none; this does not explain the tree.",
                "scopes": [{"target": "app", "include": [f"{name}/**"], "ownership": "reference"}],
                "references": [],
                "checkers": [],
                "jurisdiction": {
                    "capability": slug,
                    "implementation": f"{slug}.exploring",
                    "status": "current",
                    "entrypoints": [],
                    "grain": "subtree",
                    "meaning": "none",
                    "contract": "none",
                    "decider": "none",
                    "span": "none",
                },
            }
        )
        relations.append({"source": card_id, "type": "explains", "target": floor_id})
    return {"cards": cards, "relations": relations, "contracts": []}

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

def configure_trunk(start: Path, *, branch: str, actor: str, reason: str) -> dict[str, Any]:
    """登记/变更正主的登记主干分支（manifest project.trunk），进账本。

    start/finish 的 trunk 守卫以此为准。登记的分支必须真实存在——
    把主干登记成一个不存在的分支等于没有守卫。
    """
    actor = actor.strip()
    reason = reason.strip()
    branch = branch.strip()
    if not actor or not reason:
        raise AG2CError("governance trunk requires --actor and --reason")
    if not branch:
        raise AG2CError("governance trunk requires --branch")
    root = repository_root(start)
    from .gitops import git

    git(root, "rev-parse", "--verify", f"refs/heads/{branch}")
    manifest = load_manifest(discover_manifest(root), project_root=root)
    raw = _read_json(manifest.path)
    project = raw.setdefault("project", {})
    previous = str(project.get("trunk") or "")
    if previous == branch:
        return {"action": "update", "kind": "trunk", "changes": {}, "actor": actor, "reason": reason}
    project["trunk"] = branch
    _atomic_json(manifest.path, raw)
    try:
        load_manifest(manifest.path)
    except ConfigurationError as exc:
        project["trunk"] = previous
        _atomic_json(manifest.path, raw)
        raise AG2CError(f"updated manifest is invalid (rolled back): {exc}") from exc
    event = append_event(
        manifest.ledger_path,
        "governance-applied",
        {
            "action": "update",
            "kind": "trunk",
            "id": "trunk",
            "changes": {"trunk": {"from": previous, "to": branch}},
            "actor": actor,
            "reason": reason,
        },
    )
    return {
        "action": "update",
        "kind": "trunk",
        "changes": {"trunk": {"from": previous, "to": branch}},
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
    from .households import census_report, household_guidance, households_covering_path
    from .slicer import parse_path_spec

    households = []
    implementations = []
    try:
        report = census_report(manifest, policy)
        guidance = household_guidance(report)
        implementations = list(report.get("implementations") or [])
        selected = {str(card["id"]) for card in entry.get("cards") or []}
        matched_ids: set[str] = set()
        for spec in path_specs:
            try:
                target, path = parse_path_spec(spec, manifest)
            except Exception:
                continue
            matched_ids.update(item["id"] for item in households_covering_path(report, target, path))
        households = [
            item
            for item in guidance
            if all_mode or item["id"] in selected or item["id"] in matched_ids
        ]
    except AG2CError:
        pass
    from ag2c_gui.graph import knowledge_lineage_index

    card_dicts = [
        {
            "id": card.card_id,
            "type": card.card_type,
            "title": card.title,
            "summary": card.summary,
            "scopes": [
                {"include": list(scope.includes), "exclude": list(scope.excludes), "target": scope.target_id}
                for scope in card.scopes
            ],
            "references": list(card.references),
            "jurisdiction": card.jurisdiction,
        }
        for card in policy.cards
        if card.card_type == "knowledge"
    ]
    lineage_ids = {str(card["id"]) for card in entry.get("cards") or []}
    lineage_ids.update(item["id"] for item in households)
    reuse_menu = [
        {"id": card.card_id, "title": card.title, "provides": list(card.provides)}
        for card in policy.cards
        if card.card_id in lineage_ids and card.provides
    ]
    conventions = [
        {"id": card.card_id, "title": card.title, "conventions": card.conventions}
        for card in policy.cards
        if card.card_id in lineage_ids and card.conventions
    ]
    return {
        "route": entry["route"],
        "knowledge": entry.get("knowledge") or [],
        "cards": [
            {"id": card["id"], "type": card["type"], "title": card["title"], "summary": card["summary"]}
            for card in entry.get("cards") or []
        ],
        "households": households,
        "lineage": knowledge_lineage_index(card_dicts, selected_ids=lineage_ids),
        "implementations": implementations,
        "pending": pending.get("items") or [],
        "reuse_menu": reuse_menu,
        "conventions": conventions,
    }
