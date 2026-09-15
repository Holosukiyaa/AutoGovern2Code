"""AG2C-owned seeding: lifecycle, observation, and mechanical sowing.

Foreign projects are not trees. Enrollment plants a seed: `enroll` / `setup
--project` sows once and stops. `sow` writes room checkers whose command is
native ``unittest discover`` on the project's test folder — not
``python -m ag2c`` and not a per-project suites.py. The tree grows later,
when the project is actually used. Status is derived from Policy, never from
an agent-written map.
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
FOUNDING_PACK_GROUP = "smoke"
FOUNDING_PACK_EXAM = '''"""Pack smoke: the enrolled project root is a Git checkout."""
from pathlib import Path
import unittest


class PackSmokeTests(unittest.TestCase):
    def test_cwd_is_a_git_worktree(self) -> None:
        root = Path.cwd()
        self.assertTrue((root / ".git").exists(), f"missing .git at {root}")
'''


def is_host_project(root: Path) -> bool:
    return (root / "src" / "ag2c" / "__init__.py").is_file()


def is_ag2c_seed_command(command: tuple[str, ...] | list[str]) -> bool:
    """True for native unittest discover or the store pack runner.

    ``python -m ag2c seed run`` is the old biased shape and is not trusted.
    """
    parts = [str(item) for item in command]
    if "-m" in parts and "unittest" in parts and "discover" in parts and "-s" in parts:
        return True
    joined = " ".join(parts).replace("\\", "/")
    return "pack/run_exam.py" in joined


def pack_dir(policy_path: Path) -> Path:
    return policy_path.parent / "pack"


def discover_pack_groups(pack: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    exams = pack / "exams"
    if not exams.is_dir():
        return found
    for child in sorted(exams.iterdir()):
        if not child.is_dir() or child.name in SKIP_GROUP_NAMES:
            continue
        if not list(child.glob("test_*.py")):
            continue
        found[child.name] = child
    return found


RUN_EXAM_SOURCE = (
    '"""Run one pack exam group. cwd must be the governed project root."""\n'
    "from __future__ import annotations\n\n"
    "import sys\n"
    "import unittest\n"
    "from pathlib import Path\n\n\n"
    "def main(argv: list[str]) -> int:\n"
    "    if len(argv) < 2 or not str(argv[1]).strip():\n"
    '        print("usage: run_exam.py <group>", file=sys.stderr)\n'
    "        return 2\n"
    "    group = str(argv[1]).strip()\n"
    '    if group in {".", ".."} or any(sep in group for sep in "/\\\\"):\n'
    '        print("invalid group", file=sys.stderr)\n'
    "        return 2\n"
    '    folder = Path(__file__).resolve().parent / "exams" / group\n'
    "    if not folder.is_dir():\n"
    '        print(f"unknown pack exam group: {group}", file=sys.stderr)\n'
    "        return 2\n"
    "    root = Path.cwd()\n"
    '    for entry in (root, root / "src", root / "scripts"):\n'
    "        text = str(entry)\n"
    "        if entry.is_dir() and text not in sys.path:\n"
    "            sys.path.insert(0, text)\n"
    "    result = unittest.TextTestRunner(verbosity=1).run(\n"
    '        unittest.defaultTestLoader.discover(str(folder), pattern="test_*.py")\n'
    "    )\n"
    "    return 0 if result.wasSuccessful() else 1\n\n\n"
    'if __name__ == "__main__":\n'
    "    raise SystemExit(main(sys.argv))\n"
)


def ensure_pack_runner(pack: Path) -> Path:
    pack.mkdir(parents=True, exist_ok=True)
    runner = pack / "run_exam.py"
    runner.write_text(RUN_EXAM_SOURCE, encoding="utf-8")
    return runner


def pack_exam_command(runner: Path, group: str) -> list[str]:
    return ["python", "-B", runner.resolve().as_posix(), group]


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


def _any_test_files(root: Path) -> bool:
    for base in (root / "tests", root / "scripts" / "tests"):
        if not base.is_dir():
            continue
        if any(base.rglob("test_*.py")):
            return True
    return False


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


def ensure_founding_pack_exam(pack: Path) -> str:
    """Write a store-side smoke exam when the project has no test groups."""
    folder = pack / "exams" / FOUNDING_PACK_GROUP
    folder.mkdir(parents=True, exist_ok=True)
    exam = folder / "test_pack_smoke.py"
    if not exam.is_file():
        exam.write_text(FOUNDING_PACK_EXAM, encoding="utf-8")
    ensure_pack_runner(pack)
    return FOUNDING_PACK_GROUP


def plant_at_enrollment(root: Path) -> dict[str, Any]:
    """Sow once at enroll. Host skips. Failure does not roll back enrollment."""
    if is_host_project(root):
        return {
            "action": "skipped-host",
            "created": [],
            "skipped": [{"reason": "host organism is not sown"}],
        }
    try:
        return sow(root, actor="ag2c", reason="plant seed at enrollment")
    except AG2CError as exc:
        return {"action": "sow", "error": str(exc), "created": [], "skipped": []}


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
    pack = pack_dir(manifest.policy_path)
    pack_groups = discover_pack_groups(pack)
    if not groups and not pack_groups and not _any_test_files(root):
        ensure_founding_pack_exam(pack)
        pack_groups = discover_pack_groups(pack)
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
    if pack_groups:
        runner = ensure_pack_runner(pack)
        for name in pack_groups:
            if f"check.suite-{name}" in created:
                continue
            bind = _bind_targets(policy, name, f"pack/exams/{name}")
            if not bind:
                skipped.append({"suite": name, "reason": "no floor or knowledge card to bind"})
                continue
            checker_id = f"check.suite-{name}"
            update_checker(
                root,
                checker_id=checker_id,
                actor=actor,
                reason=reason,
                command=pack_exam_command(runner, name),
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
        "groups": sorted(set(groups) | set(pack_groups)),
        "pack": str(pack) if pack_groups else "",
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
