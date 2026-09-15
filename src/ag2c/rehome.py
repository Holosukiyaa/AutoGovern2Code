"""Move a file card's file into another room through the governed task loop.

The tray's drag-and-drop ("re-parent = re-scope") is a real refactoring: the
file physically moves with ``git mv``, Python imports rewrite across the repo,
the card's scope follows, and everything rides through task start → verify →
finish so the move can never bypass governance. A failed verification abandons
the task and rolls the card scope back, leaving the canonical checkout exactly
as it was.

v1 deliberately supports Python modules only (never ``__init__.py``): import
rewriting is textual and boundary-aware, and files using relative imports are
refused because their dot-prefixes cannot be recomputed safely yet.
"""
from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any

from .errors import AG2CError
from .gitops import git, repository_root
from .govern import _read_json
from .household_commands import (
    _context,
    _identity,
    _is_enrollment_placeholder,
    _save_policy,
    review_census,
)
from .households import _is_proper_subdir, directory_scope
from .tasks import finish_task, start_task, verify_task
from .task_orient import abandon_task

_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "dist", "build", ".retired"}
_RELATIVE_IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+\.+", re.MULTILINE)


def _cards_by_id(manifest) -> dict[str, dict]:
    raw = _read_json(manifest.policy_path)
    return {str(card.get("id")): card for card in raw.get("cards") or [] if card.get("id")}


def _card_file(card: dict) -> str:
    includes = [str(p) for scope in card.get("scopes") or [] for p in scope.get("include") or []]
    files = [pattern for pattern in includes if "*" not in pattern]
    if len(files) != 1:
        raise AG2CError(f"card does not own exactly one file: {card.get('id')}")
    return files[0]


def _room_directory(card: dict) -> str:
    roots = {
        directory_scope(str(pattern))
        for scope in card.get("scopes") or []
        for pattern in scope.get("include") or []
    }
    return min(roots, key=len) if roots else ""


def _owning_room(cards: dict[str, dict], rel_file: str, exclude: str) -> str:
    """Longest-prefix real room whose directory contains rel_file."""
    best_id = ""
    best_len = -1
    for card_id, card in cards.items():
        if card_id == exclude or card.get("type") != "knowledge" or _is_enrollment_placeholder(card):
            continue
        directory = _room_directory(card)
        if directory and rel_file.startswith(directory + "/") and len(directory) > best_len:
            best_id = card_id
            best_len = len(directory)
    return best_id


def python_module_name(root: Path, rel_file: str) -> str:
    """Dotted module for rel_file, walking up while ``__init__.py`` exists."""
    path = root / rel_file
    parts = [path.stem]
    parent = path.parent
    while parent != parent.parent and (parent / "__init__.py").is_file():
        parts.append(parent.name)
        if parent == root:
            break
        parent = parent.parent
    return ".".join(reversed(parts))


def rewrite_module_imports(root: Path, old_module: str, new_module: str) -> list[str]:
    """Rewrite every textual occurrence of a dotted module path in .py files.

    One boundary-aware pattern covers ``from x import``, ``import x``, and
    quoted patch-target strings alike; a following dot is allowed (submodule
    or attribute), a preceding word character or dot is not, so lookalikes
    such as ``other.backend.foo`` or ``backend.foo2`` stay untouched.
    """
    if old_module == new_module:
        return []
    pattern = re.compile(r"(?<![\w.])" + re.escape(old_module) + r"(?![\w])")
    changed: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if set(path.relative_to(root).parts) & _SKIP_DIRS:
            continue
        text = path.read_text(encoding="utf-8")
        updated = pattern.sub(new_module, text)
        if updated != text:
            path.write_text(updated, encoding="utf-8")
            changed.append(str(path.relative_to(root)).replace("\\", "/"))
    return changed


def _rewrite_card_scope(
    start: Path,
    card_id: str,
    old_rel: str,
    new_rel: str,
    actor: str,
    reason: str,
    event_type: str,
) -> dict:
    manifest, _policy = _context(start)
    raw = _read_json(manifest.policy_path)
    card = next((item for item in raw.get("cards") or [] if item.get("id") == card_id), None)
    if card is None:
        raise AG2CError(f"unknown card: {card_id}")
    for scope in card.get("scopes") or []:
        scope["include"] = [new_rel if pattern == old_rel else pattern for pattern in scope.get("include") or []]
    card["references"] = [new_rel if ref == old_rel else ref for ref in card.get("references") or []]
    return _save_policy(
        manifest,
        raw,
        actor,
        reason,
        event_type,
        {"card": card_id, "from": old_rel, "to": new_rel},
    )


def _normalize_subdir(value: str) -> str:
    parts = [part for part in PurePosixPath(value.strip().replace("\\", "/")).parts if part not in ("", "/")]
    if any(part in ("..", ".") for part in parts):
        raise AG2CError(f"target subdirectory must stay inside the room: {value}")
    return "/".join(parts)


def rehome_file_card(
    start: Path,
    *,
    card_id: str,
    target_room: str,
    target_subdir: str = "",
    actor: str,
    reason: str,
) -> dict[str, Any]:
    """Move a file card's file into target_room (optionally a subdirectory).

    The whole move rides one governed task: scope update first (so the task
    snapshots the final policy), then git mv + import rewrite in the worktree,
    census, verify, finish. Any failure abandons the task and rolls the scope
    back before re-raising.
    """
    actor, reason = _identity(actor, reason)
    canonical = repository_root(start)
    manifest, _policy = _context(canonical)
    cards = _cards_by_id(manifest)
    card = cards.get(card_id)
    if card is None or card.get("type") != "knowledge":
        raise AG2CError(f"unknown knowledge card: {card_id}")
    if _is_enrollment_placeholder(card):
        raise AG2CError(f"cannot rehome an enrollment placeholder: {card_id}")
    old_rel = _card_file(card)
    if not old_rel.endswith(".py"):
        raise AG2CError("rehome currently supports Python files only: " + old_rel)
    if old_rel.endswith("/__init__.py"):
        raise AG2CError("refusing to move a package marker: " + old_rel)
    if not (canonical / old_rel).is_file():
        raise AG2CError(f"card file is missing on disk: {old_rel}")
    room = cards.get(target_room)
    if room is None or room.get("type") != "knowledge" or _is_enrollment_placeholder(room):
        raise AG2CError(f"target is not a real room: {target_room}")
    room_dir = _room_directory(room)
    if not room_dir:
        raise AG2CError(f"target room has no directory scope: {target_room}")
    subdir = _normalize_subdir(target_subdir)
    target_dir = f"{room_dir}/{subdir}" if subdir else room_dir
    if target_dir != room_dir and not _is_proper_subdir(target_dir, room_dir):
        raise AG2CError(f"target subdirectory escapes the room: {target_subdir}")
    if not (canonical / target_dir).is_dir():
        raise AG2CError(f"target directory does not exist: {target_dir}")
    old_dir = old_rel.rsplit("/", 1)[0] if "/" in old_rel else ""
    if target_dir == old_dir:
        raise AG2CError("file already lives in the target directory")
    new_rel = f"{target_dir}/{PurePosixPath(old_rel).name}"
    if (canonical / new_rel).exists():
        raise AG2CError(f"target file already exists: {new_rel}")
    if _RELATIVE_IMPORT_RE.search((canonical / old_rel).read_text(encoding="utf-8")):
        raise AG2CError("file uses relative imports; rehome cannot recompute them yet: " + old_rel)
    old_module = python_module_name(canonical, old_rel)
    new_module = python_module_name(canonical, new_rel)
    old_room = _owning_room(cards, old_rel, exclude=card_id)
    new_room = _owning_room(cards, new_rel, exclude=card_id)
    census_rooms = sorted({room for room in (old_room, new_room, target_room) if room})

    goal = f"rehome {old_rel} -> {new_rel} (card {card_id} into room {target_room})"
    portrait = (
        f"完成态：{old_rel} 移到 {new_rel}，卡 {card_id} 的 scope 指向新路径，"
        f"全仓 {old_module} 引用改写为 {new_module}，verify 通过后合并；失败则全部回滚。无加料。"
    )
    _rewrite_card_scope(canonical, card_id, old_rel, new_rel, actor, reason, "card-rehome-scope")
    task_id = ""
    try:
        task = start_task(canonical, goal=goal, path_specs=[f"app:{old_rel}"], contract_specs=[], portrait=portrait)
        task_id = str(task["id"])
        worktree = Path(task["worktree"]["path"])
        (worktree / target_dir).mkdir(parents=True, exist_ok=True)
        git(worktree, "mv", old_rel, new_rel)
        rewritten = rewrite_module_imports(worktree, old_module, new_module)
        if census_rooms:
            review_census(worktree, card_ids=census_rooms, all_cards=False, actor=actor, reason=reason)
        result = verify_task(worktree)
        if not result.get("passed"):
            raise AG2CError("verification failed after rehome; the task was abandoned and the move rolled back")
        proof = (
            f"verify_task 在 worktree 通过（change_digest {result.get('change_digest')}）；"
            f"git mv {old_rel} -> {new_rel}；改写 {len(rewritten)} 个文件的模块引用。"
        )
        finish_task(canonical, task_id, message=goal, proof=proof)
    except Exception:
        if task_id:
            try:
                abandon_task(canonical, task_id, reason="rehome failed; rolling back")
            except AG2CError:
                pass
        _rewrite_card_scope(
            canonical,
            card_id,
            new_rel,
            old_rel,
            actor,
            reason + " (rollback)",
            "card-rehome-rollback",
        )
        raise
    if census_rooms:
        review_census(canonical, card_ids=census_rooms, all_cards=False, actor=actor, reason=reason)
    return {
        "card": card_id,
        "from": old_rel,
        "to": new_rel,
        "room": target_room,
        "task": task_id,
        "rewritten": rewritten,
        "merged": True,
    }
