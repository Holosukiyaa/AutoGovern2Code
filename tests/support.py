from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import bootstrap

from ag2c.config import discover_manifest, load_manifest, load_policy


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def bare_manifest(root: Path):
    """Minimal in-memory Manifest for tests that need no real policy files."""
    from ag2c.model import Manifest

    return Manifest(
        path=root / "manifest.json",
        project_id="test-proj",
        project_root=root,
        targets=[],
        ledger_path=root / "ledger.jsonl",
        policy_path=root / "policy.json",
        state_dir=root / "state",
    )


def git_project(root: Path) -> Path:
    root.mkdir(parents=True)
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "src" / "__init__.py").write_text("", encoding="utf-8")
    (root / "src" / "value.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (root / "tests" / "test_value.py").write_text(
        "import unittest\nfrom src.value import VALUE\n\n"
        "class ValueTests(unittest.TestCase):\n"
        "    def test_value(self):\n"
        "        self.assertEqual(VALUE, 1)\n",
        encoding="utf-8",
    )
    (root / ".gitignore").write_text("__pycache__/\n*.pyc\n", encoding="utf-8")
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.name", "AG2C Test")
    _git(root, "config", "user.email", "ag2c-test@example.invalid")
    _git(root, "add", "--all")
    _git(root, "commit", "-m", "initial")
    return root.resolve()


def external_manifest(root: Path):
    return load_manifest(discover_manifest(root))


def external_state(root: Path) -> Path:
    return external_manifest(root).state_dir


def write_project(root: Path, *, extra_file: bool = False, gated: bool = False):
    """Build a minimal governed project fixture.

    gated=True upgrades the fixture to production gate fidelity (夹具保真度,
    see tests/test_sunset.py's _canary_project): knowledge cards get a
    jurisdiction, every room explains its floor, and household_required=true
    is declared. Any test that exercises gate logic (run_checks / verify_task /
    enforce_households / finish_task) must use this mode — a fixture more
    lenient than production is itself a hole. Pair it with record_census()
    after the final policy mutation so the household gate sees fresh census.
    """
    (root / ".ag2c").mkdir(parents=True)
    (root / "src" / "api").mkdir(parents=True)
    (root / "src" / "worker").mkdir(parents=True)
    (root / "src" / "api" / "service.py").write_text("VALUE = 'api'\n", encoding="utf-8")
    (root / "src" / "worker" / "job.py").write_text("VALUE = 'worker'\n", encoding="utf-8")
    if extra_file:
        (root / "src" / "other.py").write_text("VALUE = 'other'\n", encoding="utf-8")
    manifest = {
        "schema": "ag2c.manifest.v1",
        "project": {"id": "test-project"},
        "policy": ".ag2c/policy.json",
        "state_dir": ".ag2c/state",
        "ledger": ".ag2c/ledger.jsonl",
        "targets": [
            {"id": "app", "path": ".", "governed_roots": ["src"], "exclude": []}
        ],
    }
    success = [sys.executable, "-c", "print('checker passed')"]
    policy = {
        "schema": "ag2c.policy.v1",
        "cards": [
            {
                "id": "constitution.project",
                "type": "constitution",
                "title": "Constitution",
                "summary": "Global project invariants.",
            },
            {
                "id": "floor.api",
                "type": "floor",
                "title": "API",
                "summary": "Owns API source.",
                "scopes": [{"target": "app", "include": ["src/api/**"], "ownership": "primary"}],
                "checkers": ["check.floor"],
            },
            {
                "id": "floor.worker",
                "type": "floor",
                "title": "Worker",
                "summary": "Owns worker source.",
                "scopes": [{"target": "app", "include": ["src/worker/**"], "ownership": "primary"}],
                "checkers": ["check.floor"],
            },
            {
                "id": "knowledge.worker",
                "type": "knowledge",
                "title": "Worker navigation",
                "summary": "Explains worker source.",
                "scopes": [{"target": "app", "include": ["src/worker/**"], "ownership": "reference"}],
                "references": ["src/worker/job.py"],
            },
            {
                "id": "boundary.jobs",
                "type": "boundary",
                "title": "Jobs boundary",
                "summary": "Connects the API producer to the worker consumer.",
                "checkers": ["check.boundary"],
            },
            {
                "id": "scenario.jobs",
                "type": "scenario",
                "title": "Jobs scenario",
                "summary": "Proves the worker consumes a submitted job.",
                "checkers": ["check.scenario"],
            },
        ],
        "relations": [
            {"source": "floor.worker", "type": "depends_on", "target": "floor.api"},
            {"source": "knowledge.worker", "type": "explains", "target": "floor.worker"},
            {"source": "boundary.jobs", "type": "producer", "target": "floor.api"},
            {"source": "boundary.jobs", "type": "consumer", "target": "floor.worker"},
        ],
        "contracts": [
            {
                "target": "app",
                "id": "jobs.submit",
                "version": "1.0.0",
                "boundary": "boundary.jobs",
                "scenarios": ["scenario.jobs"],
            }
        ],
        "checkers": [
            {"id": "check.floor", "stage": "floor", "target": "app", "command": success},
            {"id": "check.boundary", "stage": "boundary", "target": "app", "command": success},
            {"id": "check.scenario", "stage": "scenario", "target": "app", "command": success},
        ],
    }
    if gated:
        _apply_gate_fidelity(policy)
    manifest_path = root / ".ag2c" / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (root / ".ag2c" / "policy.json").write_text(json.dumps(policy, indent=2), encoding="utf-8")
    loaded_manifest = load_manifest(manifest_path)
    return loaded_manifest, load_policy(loaded_manifest)


def _jurisdiction(capability: str, implementation: str) -> dict:
    return {
        "capability": capability,
        "implementation": implementation,
        "status": "current",
        "entrypoints": [],
        "grain": "subtree",
        "meaning": "named",
        "contract": "none",
        "decider": "none",
        "span": "folder",
    }


def _apply_gate_fidelity(policy: dict) -> None:
    """Mutate a write_project policy dict into household_required=true shape."""
    for card in policy["cards"]:
        if card.get("id") == "knowledge.worker":
            card["jurisdiction"] = _jurisdiction("worker", "worker.main")
    policy["cards"].append(
        {
            "id": "knowledge.api",
            "type": "knowledge",
            "title": "API navigation",
            "summary": "Explains api source.",
            "scopes": [{"target": "app", "include": ["src/api/**"], "ownership": "reference"}],
            "references": [],
            "jurisdiction": _jurisdiction("api", "api.main"),
        }
    )
    policy["relations"].append({"source": "knowledge.api", "type": "explains", "target": "floor.api"})
    policy["household_required"] = True


def record_census(root: Path, *, actor: str = "tester", reason: str = "fixture census") -> None:
    """git init (idempotent) + record census for every card + rebuild the index.

    Call after the FINAL policy mutation, right before the gate entry under
    test: the household gate refuses stale census, exactly like production
    verify does. git init and the census writes both dirty the worktree, so
    the index is rebuilt last to keep compile_slice's freshness check happy.
    """
    import subprocess

    if not (root / ".git").exists():
        subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
    from ag2c.config import load_manifest, load_policy
    from ag2c.household_commands import review_census
    from ag2c.index import build_index

    manifest = load_manifest(root / ".ag2c" / "manifest.json")
    policy = load_policy(manifest)
    build_index(manifest, policy)
    review_census(root, card_ids=[], all_cards=True, actor=actor, reason=reason)
    build_index(manifest, policy)
