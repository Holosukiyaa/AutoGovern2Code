"""AG2C-owned seeding: lifecycle, observation, and mechanical sowing.

Foreign projects are not trees. Enrollment plants a seed. `ag2c seed sow`
writes room checkers whose command is native ``unittest discover`` on the
project's test folder — not ``python -m ag2c`` and not a per-project
suites.py. Status is derived from Policy, never from an agent-written map.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

from .acceptance import GROWTH_SLICED, assess_verification_growth
from .errors import AG2CError
from .model import Card, Policy
from .util import path_matches

PHASE_PLANTED = "planted"
PHASE_MAPPED = "mapped"
PHASE_GROWING = "growing"
PHASE_SLICED = "sliced"

SOWER_NONE = "none"
SOWER_AG2C = "ag2c"
SOWER_FOREIGN = "foreign"
SOWER_HOST = "host"

PHASE_SUMMARIES = {
    PHASE_PLANTED: "enrolled; product tests are still one blob and the card map is thin",
    PHASE_MAPPED: "rooms/cards exist; product tests are still one blob",
    PHASE_GROWING: "room suites exist; verification is not yet sliced",
    PHASE_SLICED: "a knowledge-bound product test uses a command distinct from the always-on blob",
}

SKIP_GROUP_NAMES = {"__pycache__", "fixtures", "data"}


def is_host_project(root: Path) -> bool:
    return (root / "src" / "ag2c" / "__init__.py").is_file()


def is_ag2c_seed_command(command: tuple[str, ...] | list[str]) -> bool:
    """True when the checker is native unittest discover (AG2C-sown shape).

    ``python -m ag2c seed run`` is the old biased shape and is not trusted.
    """
    parts = [str(item) for item in command]
    return "-m" in parts and "unittest" in parts and "discover" in parts and "-s" in parts


def is_foreign_suite_command(command: tuple[str, ...] | list[str]) -> bool:
    if is_ag2c_seed_command(command):
        return False
    parts = [str(item) for item in command]
    text = " ".join(parts)
    if "suites.py" in text or "run_conformance.py" in text:
        return True
    return "-m" in parts and "ag2c" in parts and "seed" in parts


def native_discover_command(relative: str) -> list[str]:
    folder = relative.replace("\\", "/").strip("/")
    return ["python", "-B", "-m", "unittest", "discover", "-s", folder, "-p", "test_*.py"]


def discover_groups(root: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for base in (root / "scripts" / "tests", root / "tests"):
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if not child.is_dir() or child.name in SKIP_GROUP_NAMES:
                continue
            if not list(child.glob("test_*.py")):
                continue
            found.setdefault(child.name, child)
    return found


def _sower_from_checkers(policy: Policy, *, host: bool) -> str:
    if host:
        return SOWER_HOST
    has_ag2c = any(is_ag2c_seed_command(checker.command) for checker in policy.checkers)
    has_foreign = any(is_foreign_suite_command(checker.command) for checker in policy.checkers)
    if has_ag2c:
        return SOWER_AG2C
    if has_foreign:
        return SOWER_FOREIGN
    return SOWER_NONE


def assess_seed(policy: Policy, *, project_root: Path | None = None) -> dict[str, Any]:
    growth = assess_verification_growth(policy)
    host = bool(project_root and is_host_project(project_root))
    sower = _sower_from_checkers(policy, host=host)
    suite_like = sower in {SOWER_AG2C, SOWER_FOREIGN, SOWER_HOST} or any(
        str(checker.checker_id).startswith("check.suite-") for checker in policy.checkers
    )
    named_map = policy.coverage.level == "structured" or any(
        card.card_type == "knowledge" and card.jurisdiction for card in policy.cards
    )
    if growth["status"] == GROWTH_SLICED:
        phase = PHASE_SLICED
    elif suite_like:
        phase = PHASE_GROWING
    elif named_map:
        phase = PHASE_MAPPED
    else:
        phase = PHASE_PLANTED
    trusted = sower == SOWER_AG2C and phase == PHASE_SLICED
    return {
        "phase": phase,
        "sower": sower,
        "trusted": trusted,
        "summary": PHASE_SUMMARIES[phase],
        "verification_growth": growth["status"],
        "verification_growth_reason": growth["reason"],
        "map_level": policy.coverage.level,
    }


def format_seed_status(status: dict[str, Any]) -> str:
    trusted = "yes" if status.get("trusted") else "no"
    return (
        f"Seed: {status['phase']}\n"
        f"Sower: {status['sower']}\n"
        f"Trusted: {trusted}\n"
        f"{status['summary']}"
    )


def _relative_posix(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _card_covers(card: Card, relative: str) -> bool:
    sample = f"{relative}/test_x.py"
    return any(path_matches(sample, include) for scope in card.scopes for include in scope.includes)


def _bind_targets(policy: Policy, group: str, relative: str) -> list[str]:
    bound: list[str] = []
    wanted = {f"knowledge.scripts-tests-{group}", f"knowledge.tests-{group}", f"knowledge.{group}"}
    for card in policy.cards:
        if card.card_id in wanted and card.jurisdiction is not None:
            bound.append(card.card_id)
        elif card.card_type == "knowledge" and card.jurisdiction is not None and _card_covers(card, relative):
            bound.append(card.card_id)
    floors = [card.card_id for card in policy.cards if card.card_type == "floor" and _card_covers(card, relative)]
    if not floors:
        floors = [card.card_id for card in policy.cards if card.card_type == "floor"][:1]
    for floor_id in floors:
        if floor_id not in bound:
            bound.append(floor_id)
    return list(dict.fromkeys(bound))


def sow(start: Path, *, actor: str, reason: str) -> dict[str, Any]:
    from .config import discover_manifest, load_manifest, load_policy
    from .gitops import repository_root
    from .govern import update_checker

    actor = actor.strip()
    reason = reason.strip()
    if not actor or not reason:
        raise AG2CError("seed sow requires --actor and --reason")
    root = repository_root(start)
    if is_host_project(root):
        raise AG2CError("host organism is not sown; it grew in place")
    manifest = load_manifest(discover_manifest(root), project_root=root)
    policy = load_policy(manifest)
    groups = discover_groups(root)
    created: list[str] = []
    skipped: list[dict[str, str]] = []
    for name, folder in groups.items():
        relative = _relative_posix(root, folder)
        bind = _bind_targets(policy, name, relative)
        if not bind:
            skipped.append({"suite": name, "reason": "no floor or knowledge card to bind"})
            continue
        checker_id = f"check.suite-{name}"
        update_checker(
            root,
            checker_id=checker_id,
            actor=actor,
            reason=reason,
            command=native_discover_command(relative),
            parse="unittest",
            bind=bind,
        )
        created.append(checker_id)
        policy = load_policy(load_manifest(discover_manifest(root), project_root=root))
    status = assess_seed(policy, project_root=root)
    return {
        "action": "sow",
        "actor": actor,
        "reason": reason,
        "created": created,
        "skipped": skipped,
        "groups": sorted(groups),
        "seed": status,
    }


def run_suite(root: Path, name: str) -> int:
    name = name.strip()
    groups = discover_groups(root)
    folder = groups.get(name)
    if folder is None:
        expected = ", ".join(sorted(groups)) or "(none)"
        print(f"unknown suite: {name}; expected one of {expected}", file=sys.stderr)
        return 2
    for entry in (root, root / "src", root / "scripts"):
        text = str(entry)
        if entry.is_dir() and text not in sys.path:
            sys.path.insert(0, text)
    suite = unittest.TestLoader().discover(str(folder), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1
