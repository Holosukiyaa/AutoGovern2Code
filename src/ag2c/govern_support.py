"""Extracted by flatten-split."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from .util import atomic_json_write

PENDING_FILENAME = "governance-pending.json"

DOC_NAMES = ("README.md", "README.zh-CN.md", "README.en.md", "CONTRIBUTING.md", "CHANGELOG.md", "AGENTS.md")

DOC_DIRS = ("docs", "doc", "handbook")

BOUNDARY_HINTS = {"api", "routes", "graphql", "proto", "openapi", "handlers", "endpoints"}

SKIP_DIRS = {".git", "node_modules", "dist", "build", ".next", "__pycache__", ".venv", "venv"}

MAX_KNOWLEDGE_CARDS = 30

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

_atomic_json = atomic_json_write

def _read_json(path: Path) -> dict[str, Any]:
    from .util import read_json

    return read_json(path, what="governance file")

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

def _card_include_roots(card: dict[str, Any]) -> set[str]:
    from .households import directory_scope

    roots: set[str] = set()
    for scope in card.get("scopes") or []:
        for pattern in scope.get("include") or []:
            text = str(pattern)
            if text.endswith("/**") or text == "**":
                roots.add(directory_scope(text))
    return roots

def _jurisdiction_include_roots(cards: list[Any]) -> set[str]:
    roots: set[str] = set()
    for card in cards:
        if not isinstance(card, dict) or not card.get("jurisdiction"):
            continue
        roots.update(_card_include_roots(card))
    return roots

def _include_roots_overlap(left: set[str], right: set[str]) -> bool:
    from .households import _is_proper_subdir

    for first in left:
        for second in right:
            if first == second or _is_proper_subdir(first, second) or _is_proper_subdir(second, first):
                return True
    return False

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
