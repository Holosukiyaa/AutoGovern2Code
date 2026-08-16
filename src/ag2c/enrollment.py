from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .config import MANIFEST_SCHEMA, POLICY_SCHEMA, discover_manifest, load_manifest, load_policy
from .errors import AG2CError
from .gitops import canonical_worktree, current_branch, git, repository_root, status_entries
from .harnesses import SKILL_NAME, install_skill, install_skills, skill_digest, skill_source
from .index import build_index
from .lifecycle import LifecycleTransaction, lifecycle_pending, recover_lifecycle
from .ledger import append_event
from .storage import configured_manifest, git_private_path, project_store, register_project, unregister_project
from .util import digest_file

ENROLLMENT_SCHEMA = "ag2c.enrollment.v1"
ACTIVATION_SCHEMA = "ag2c.activation.v1"
AGENTS_BEGIN = "<!-- AG2C:BEGIN -->"
AGENTS_END = "<!-- AG2C:END -->"
IGNORE_BEGIN = "# AG2C:BEGIN"
IGNORE_END = "# AG2C:END"
LEGACY_AGENTS_BEGIN = "<!-- DEG:BEGIN -->"
LEGACY_AGENTS_END = "<!-- DEG:END -->"
LEGACY_IGNORE_BEGIN = "# DEG:BEGIN"
LEGACY_IGNORE_END = "# DEG:END"

AGENTS_BLOCK = f"""{AGENTS_BEGIN}
# AutoGovern2Code managed engineering

This repository is enrolled in AG2C. For every request that may change source,
tests, documentation, configuration, dependencies, or generated deliverables:

1. Use `${SKILL_NAME}` before the first write.
2. Let the Skill repair local activation before starting a task.
3. Do not edit this canonical checkout.
4. Start an AG2C task and edit only the returned external Git worktree.
5. Run AG2C verification after the final change.
6. Finish through AG2C so verified commits are fast-forwarded into this checkout.

Do not claim completion without a valid AG2C task record and verification evidence.
If AG2C blocks an action, fix the cause; never bypass the guard, checker, or ledger.
{AGENTS_END}
"""

CLAUDE_BLOCK = f"""{AGENTS_BEGIN}
# AutoGovern2Code managed engineering

This repository is enrolled in AG2C. Before the first write for any source,
test, documentation, configuration, dependency, or generated-file change:

1. Invoke `/{SKILL_NAME}` and let it repair local activation.
2. Do not edit this canonical checkout.
3. Start an AG2C task and edit only its returned external Git worktree.
4. Verify the final change and finish through AG2C.

Never bypass AG2C guards, trusted checks, receipts, or evidence.
{AGENTS_END}
"""

IGNORE_BLOCK = f"""{IGNORE_BEGIN}
.ag2c/state/
.ag2c/ledger.jsonl
.ag2c/ledger.jsonl.lock
{IGNORE_END}
"""

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _project_id(root: Path) -> str:
    value = re.sub(r"[^a-z0-9._-]+", "-", root.name.lower()).strip("-.")
    return value or "project"


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        handle.write(content)
    os.replace(temporary, path)


def _replace_block(path: Path, begin: str, end: str, block: str) -> None:
    if path.is_file():
        with path.open("r", encoding="utf-8", newline="") as handle:
            original = handle.read()
    else:
        original = ""
    newline = "\r\n" if "\r\n" in original else "\n"
    rendered = block.rstrip().replace("\n", newline)
    if begin in original or end in original:
        start = original.find(begin)
        finish = original.find(end, start)
        if start < 0 or finish < 0:
            raise AG2CError(f"cannot update malformed AG2C block in {path}")
        finish += len(end)
        prefix = original[:start].rstrip("\r\n")
        separator = newline * 2 if prefix else ""
        content = prefix + separator + rendered + original[finish:]
    else:
        content = original.rstrip("\r\n") + (newline * 2 if original.strip() else "") + rendered + newline
    _write_text(path, content)


def _remove_block(path: Path, begin: str, end: str) -> None:
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8", newline="") as handle:
        original = handle.read()
    start = original.find(begin)
    finish = original.find(end, start)
    if start < 0 and finish < 0:
        return
    if start < 0 or finish < 0:
        raise AG2CError(f"cannot remove malformed legacy AG2C block in {path}")
    finish += len(end)
    content = (original[:start].rstrip("\r\n") + original[finish:]).lstrip("\r\n")
    newline = "\r\n" if "\r\n" in original else "\n"
    _write_text(path, content.rstrip("\r\n") + (newline if content else ""))


def _tracked_roots(root: Path) -> list[str]:
    tracked = [line.replace("\\", "/") for line in str(git(root, "ls-files")).splitlines()]
    candidates: dict[str, bool] = {}
    for relative in tracked:
        if relative in {"AGENTS.md", "CLAUDE.md", ".gitignore"} or relative.startswith((".ag2c/", ".deg/")):
            continue
        first, separator, _ = relative.partition("/")
        candidates[first] = bool(separator) or (root / first).is_dir()
    if not candidates:
        for child in sorted(root.iterdir(), key=lambda item: item.name):
            if child.name not in {".git", ".ag2c", ".deg", ".gitignore", "AGENTS.md", "CLAUDE.md"}:
                candidates[child.name] = child.is_dir()
    if not candidates:
        raise AG2CError("cannot enroll an empty project; add the initial project files first")
    return sorted(candidates)


def _area_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "area"
    return slug[:40]


def _baseline_cards(root: Path, project_roots: list[str], checker_ids: list[str]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = [
        {
            "id": "constitution.project",
            "type": "constitution",
            "title": "Managed project invariants",
            "summary": "All changes use AG2C routing, isolated worktrees, verified checks, and evidence-backed integration.",
            "references": [],
        }
    ]
    top_level_files = [name for name in project_roots if not (root / name).is_dir()]
    directories = [name for name in project_roots if (root / name).is_dir()]
    used_ids = {"constitution.project", "floor.root"}
    if top_level_files:
        cards.append(
            {
                "id": "floor.root",
                "type": "floor",
                "title": "Project root files",
                "summary": "Conservative ownership for tracked files at the project root.",
                "scopes": [{"target": "app", "include": top_level_files, "ownership": "primary"}],
                "checkers": checker_ids,
                "references": [],
            }
        )
    for name in directories:
        base_id = f"floor.{_area_slug(name)}"
        card_id = base_id
        if card_id in used_ids:
            card_id = f"{base_id}-{hashlib.sha256(name.encode('utf-8')).hexdigest()[:6]}"
        used_ids.add(card_id)
        cards.append(
            {
                "id": card_id,
                "type": "floor",
                "title": f"{name} area",
                "summary": f"Conservative ownership for the detected top-level {name} project area.",
                "scopes": [{"target": "app", "include": [f"{name}/**"], "ownership": "primary"}],
                "checkers": checker_ids,
                "references": [],
            }
        )
    if len(cards) == 1:
        cards.append(
            {
                "id": "floor.project",
                "type": "floor",
                "title": "Project implementation",
                "summary": "Conservative ownership for the complete project.",
                "scopes": [{"target": "app", "include": ["**"], "ownership": "primary"}],
                "checkers": checker_ids,
                "references": [],
            }
        )
    return cards


def _native_checkers(root: Path) -> list[dict[str, Any]]:
    checkers: list[dict[str, Any]] = [
        {
            "id": "check.diff",
            "stage": "floor",
            "target": "app",
            "command": ["git", "diff", "--check"],
            "cwd": ".",
            "timeout": 60,
        }
    ]
    if (root / "go.mod").is_file():
        checkers.append(
            {"id": "check.go", "stage": "floor", "target": "app", "command": ["go", "test", "./..."], "cwd": ".", "timeout": 600}
        )
    if (root / "Cargo.toml").is_file():
        checkers.append(
            {"id": "check.rust", "stage": "floor", "target": "app", "command": ["cargo", "test"], "cwd": ".", "timeout": 900}
        )
    package_json = root / "package.json"
    if package_json.is_file():
        try:
            scripts = json.loads(package_json.read_text(encoding="utf-8")).get("scripts", {})
        except (OSError, json.JSONDecodeError):
            scripts = {}
        if isinstance(scripts, dict) and isinstance(scripts.get("test"), str) and "no test specified" not in scripts["test"]:
            command = (
                ["pnpm", "test"] if (root / "pnpm-lock.yaml").is_file()
                else ["yarn", "test"] if (root / "yarn.lock").is_file()
                else ["bun", "test"] if (root / "bun.lockb").is_file() or (root / "bun.lock").is_file()
                else ["npm", "test"]
            )
            checkers.append(
                {"id": "check.node", "stage": "floor", "target": "app", "command": command, "cwd": ".", "timeout": 900}
            )
    if (root / "tests").is_dir() and any(root.glob("**/test*.py")):
        pyproject = root / "pyproject.toml"
        uses_pytest = (
            (root / "pytest.ini").is_file()
            or (root / "conftest.py").is_file()
            or (pyproject.is_file() and "pytest" in pyproject.read_text(encoding="utf-8", errors="ignore"))
        )
        command = (
            ["python", "-B", "-m", "pytest"]
            if uses_pytest
            else ["python", "-B", "-m", "unittest", "discover", "-s", "tests"]
        )
        checkers.append(
            {"id": "check.python", "stage": "floor", "target": "app", "command": command, "cwd": ".", "timeout": 900}
        )
    return checkers


def _activation_path(canonical: Path) -> Path:
    manifest = load_manifest(discover_manifest(canonical))
    return manifest.state_dir / "activation.json"


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _runtime_command() -> list[str]:
    executable = str(Path(sys.executable).resolve())
    if getattr(sys, "frozen", False):
        return [executable]
    return [executable, "-m", "ag2c"]


def activate_project(
    start: Path,
    *,
    skill_root: Path | None = None,
    harnesses: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    root = repository_root(start)
    canonical = canonical_worktree(root)
    if root != canonical:
        raise AG2CError(f"activate AG2C from the canonical worktree: {canonical}")
    manifest_path = discover_manifest(canonical)
    manifest = load_manifest(manifest_path)
    enrollment_path = manifest_path.parent / "enrollment.json"
    if not enrollment_path.is_file():
        raise AG2CError("project is not enrolled in AG2C")
    previous = str(git(canonical, "config", "--get", "core.hooksPath", check=False)).strip()
    hooks = (manifest.state_dir / "hooks").resolve()
    hooks.mkdir(parents=True, exist_ok=True)
    hook = hooks / "pre-commit"
    expected = str(hooks)
    activation_path = _activation_path(canonical)
    old_activation: dict[str, Any] = {}
    if activation_path.is_file():
        old_activation = json.loads(activation_path.read_text(encoding="utf-8"))
    if previous == expected:
        previous = str(old_activation.get("previous_hooks_path", ""))
    elif not previous:
        common_dir = Path(str(git(canonical, "rev-parse", "--path-format=absolute", "--git-common-dir")).strip())
        default_hooks = (common_dir / "hooks").resolve()
        if (default_hooks / "pre-commit").is_file():
            previous = str(default_hooks)
    delegate: Path | None = None
    if previous:
        delegate_root = Path(previous)
        if not delegate_root.is_absolute():
            delegate_root = (canonical / delegate_root).resolve()
        candidate = delegate_root / "pre-commit"
        if candidate.is_file() and candidate.resolve() != hook.resolve():
            delegate = candidate.resolve()
    runtime_command = _runtime_command()
    rendered_runtime = " ".join(_shell_quote(Path(item).as_posix() if index == 0 else item) for index, item in enumerate(runtime_command))
    script = f"#!/bin/sh\n{rendered_runtime} guard pre-commit || exit $?\n"
    if delegate is not None:
        script += f"{_shell_quote(delegate.as_posix())} \"$@\"\n"
    _write_text(hook, script)
    try:
        hook.chmod(0o755)
    except OSError:
        pass
    skills = install_skills(skill_root, harnesses)
    primary_skill = skills[0]
    git(canonical, "config", "core.hooksPath", expected)
    activation = {
        "schema": ACTIVATION_SCHEMA,
        "activated_at": _now(),
        "canonical_root": str(canonical),
        "python_path": str(Path(sys.executable).resolve()),
        "runtime_command": runtime_command,
        "previous_hooks_path": previous,
        "guard_digest": digest_file(hook),
        "skill_path": primary_skill["path"],
        "skill_digest": primary_skill["digest"],
        "skills": skills,
    }
    _write_json(activation_path, activation)
    policy = load_policy(manifest)
    build_index(manifest, policy)
    append_event(
        manifest.ledger_path,
        "project-activated",
        {"canonical_root": str(canonical), "skill_digests": {item["harness"]: item["digest"] for item in skills}},
    )
    return activation


def enroll_project(
    start: Path,
    *,
    project_id: str | None = None,
    skill_root: Path | None = None,
    harnesses: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    root = repository_root(start)
    if root != canonical_worktree(root):
        raise AG2CError("enroll AG2C from the canonical worktree")
    recovery = {"action": "none"}
    if configured_manifest(root) is not None:
        raise AG2CError("project is already enrolled; run `ag2c upgrade`")
    if (root / ".ag2c" / "enrollment.json").exists() or (root / ".deg" / "enrollment.json").exists():
        raise AG2CError("project contains a legacy enrollment; run `ag2c upgrade`")
    project_id = project_id or _project_id(root)
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", project_id):
        raise AG2CError("project id must contain only lowercase letters, digits, dots, underscores, and hyphens")
    project_roots = _tracked_roots(root)
    checkers = _native_checkers(root)
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "project": {"id": project_id, "root": str(root)},
        "policy": "policy.json",
        "state_dir": "state",
        "ledger": "ledger.jsonl",
        "targets": [
            {
                "id": "app",
                "path": ".",
                "governed_roots": ["."],
                "exclude": [],
            }
        ],
    }
    checker_ids = [item["id"] for item in checkers]
    policy = {
        "schema": POLICY_SCHEMA,
        "coverage": {
            "level": "baseline",
            "strategy": "conservative",
            "managed_by": "ag2c",
            "areas": project_roots,
        },
        "cards": _baseline_cards(root, project_roots, checker_ids),
        "relations": [],
        "contracts": [],
        "checkers": checkers,
    }
    enrollment = {
        "schema": ENROLLMENT_SCHEMA,
        "project_id": project_id,
        "enrolled_at": _now(),
        "skill": SKILL_NAME,
        "tool_version": __version__,
    }
    store = project_store(root)
    if store.exists() and any(store.iterdir()):
        raise AG2CError(f"external AG2C project store already exists: {store}")
    try:
        store.mkdir(parents=True, exist_ok=True)
        manifest_path = store / "manifest.json"
        _write_json(manifest_path, manifest)
        _write_json(store / "policy.json", policy)
        _write_json(store / "enrollment.json", enrollment)
        loaded_manifest = load_manifest(manifest_path)
        load_policy(loaded_manifest)
        registration = register_project(root, project_id=project_id, manifest=manifest_path)
        event = append_event(
            loaded_manifest.ledger_path,
            "project-enrolled",
            {
                "project_id": project_id,
                "commit": str(git(root, "rev-parse", "HEAD")).strip(),
                "governed_roots": project_roots,
                "storage": "external",
            },
        )
        activation = activate_project(root, skill_root=skill_root, harnesses=harnesses)
    except Exception:
        unregister_project(root, remove_data=True)
        if store.is_dir():
            shutil.rmtree(store)
        raise
    return {
        "project_id": project_id,
        "root": str(root),
        "project_key": registration["key"],
        "store": str(store),
        "working_tree_changed": False,
        "skill_path": activation["skill_path"],
        "skill_paths": [item["path"] for item in activation["skills"]],
        "ledger_event": event["event_digest"],
        "recovery": recovery,
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AG2CError(f"cannot read AG2C lifecycle file {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AG2CError(f"AG2C lifecycle file must contain an object: {path}")
    return value


def _replace_legacy_namespace(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _replace_legacy_namespace(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_legacy_namespace(item) for item in value]
    if not isinstance(value, str):
        return value
    if value == "deg":
        return "ag2c"
    return (
        value.replace(".deg/", ".ag2c/")
        .replace("deg-governed-development", SKILL_NAME)
        .replace("deg.", "ag2c.")
        .replace("DEG", "AG2C")
    )


def _upgrade_python_checkers(policy: dict[str, Any]) -> bool:
    changed = False
    for checker in policy.get("checkers", []):
        if not isinstance(checker, dict):
            continue
        command = checker.get("command")
        if (
            isinstance(command, list)
            and len(command) >= 3
            and command[0] in {"python", "python3"}
            and command[1] == "-m"
            and command[2] in {"pytest", "unittest"}
        ):
            checker["command"] = [command[0], "-B", *command[1:]]
            changed = True
    return changed


def _upgrade_generated_policy(root: Path, policy: dict[str, Any]) -> bool:
    changed = _upgrade_python_checkers(policy)
    project_roots = _tracked_roots(root)
    coverage = policy.get("coverage")
    card_ids = {
        str(card.get("id"))
        for card in policy.get("cards", [])
        if isinstance(card, dict)
    }
    legacy_generated = card_ids == {"constitution.project", "floor.project"} and not policy.get("relations") and not policy.get("contracts")
    if coverage is None and legacy_generated:
        coverage = {
            "level": "baseline",
            "strategy": "conservative",
            "managed_by": "ag2c",
            "areas": project_roots,
        }
        policy["coverage"] = coverage
        changed = True
    if isinstance(coverage, dict) and coverage.get("managed_by") == "ag2c" and coverage.get("level") == "baseline":
        detected_checkers = _native_checkers(root)
        if policy.get("checkers") != detected_checkers:
            policy["checkers"] = detected_checkers
            changed = True
        floor_checkers = [str(item["id"]) for item in detected_checkers]
        cards = _baseline_cards(root, project_roots, floor_checkers)
        expected_coverage = {
            "level": "baseline",
            "strategy": "conservative",
            "managed_by": "ag2c",
            "areas": project_roots,
        }
        if policy.get("cards") != cards:
            policy["cards"] = cards
            changed = True
        if coverage != expected_coverage:
            policy["coverage"] = expected_coverage
            changed = True
    return changed


def _maintenance_commit(root: Path, message: str, paths: list[str]) -> str | None:
    changed = str(git(root, "status", "--porcelain=v1", "--", *paths)).strip()
    if not changed:
        return None
    git(root, "add", "--all")
    git(root, "-c", "core.hooksPath=", "commit", "-m", message)
    return str(git(root, "rev-parse", "HEAD")).strip()


def _remove_managed_entry(path: Path, begin: str, end: str, *, remove_empty: bool = False) -> None:
    _remove_block(path, begin, end)
    if remove_empty and path.is_file() and not path.read_text(encoding="utf-8").strip():
        path.unlink()


def _external_manifest(root: Path, raw: dict[str, Any]) -> dict[str, Any]:
    value = dict(raw)
    project = dict(value.get("project", {}))
    project["root"] = str(root.resolve())
    value["project"] = project
    value["policy"] = "policy.json"
    value["state_dir"] = "state"
    value["ledger"] = "ledger.jsonl"
    for target in value.get("targets", []):
        if not isinstance(target, dict):
            continue
        excludes = target.get("exclude", [])
        target["exclude"] = [
            item for item in excludes
            if isinstance(item, str) and not item.startswith((".ag2c/", ".deg/"))
        ]
    return value


def _external_policy(root: Path, raw: dict[str, Any]) -> dict[str, Any]:
    value = dict(raw)
    _upgrade_generated_policy(root, value)
    for card in value.get("cards", []):
        if not isinstance(card, dict):
            continue
        references = card.get("references")
        if isinstance(references, list):
            card["references"] = [item for item in references if item not in {"AGENTS.md", "CLAUDE.md"}]
    return value


def _active_task_ids(source: Path) -> list[str]:
    directory = source / "state" / "tasks"
    result: list[str] = []
    if directory.is_dir():
        for path in directory.glob("*.json"):
            task = _read_json(path)
            if task.get("state") == "active":
                result.append(str(task.get("id", path.stem)))
    return sorted(result)


def _restore_previous_hook(root: Path, source: Path) -> None:
    actual = str(git(root, "config", "--get", "core.hooksPath", check=False)).strip()
    if actual != str((source / "state" / "hooks").resolve()):
        return
    activation_path = source / "state" / "activation.json"
    activation = _read_json(activation_path) if activation_path.is_file() else {}
    previous = str(activation.get("previous_hooks_path", ""))
    if previous:
        git(root, "config", "core.hooksPath", previous)
    else:
        git(root, "config", "--unset-all", "core.hooksPath", check=False)


def _externalize_project(
    root: Path,
    source: Path,
    *,
    legacy_deg: bool,
    skill_root: Path | None,
    harnesses: tuple[str, ...] | None,
) -> dict[str, Any]:
    active_tasks = _active_task_ids(source)
    if active_tasks:
        raise AG2CError("finish active governance tasks before externalizing: " + ", ".join(active_tasks))
    dirty = status_entries(root)
    if dirty:
        raise AG2CError("externalization requires a clean canonical worktree; commit or stash: " + ", ".join(dirty))
    store = project_store(root)
    if store.exists() and any(store.iterdir()):
        raise AG2CError(f"external AG2C project store already exists: {store}")
    manifest_raw = _read_json(source / "manifest.json")
    policy_raw = _read_json(source / "policy.json")
    enrollment_raw = _read_json(source / "enrollment.json")
    if legacy_deg:
        manifest_raw = _replace_legacy_namespace(manifest_raw)
        policy_raw = _replace_legacy_namespace(policy_raw)
        enrollment_raw = _replace_legacy_namespace(enrollment_raw)
    enrollment_raw.update({"schema": ENROLLMENT_SCHEMA, "skill": SKILL_NAME, "tool_version": __version__})
    manifest_raw = _external_manifest(root, manifest_raw)
    policy_raw = _external_policy(root, policy_raw)
    project_id = str(enrollment_raw.get("project_id") or manifest_raw.get("project", {}).get("id") or _project_id(root))
    paths = ["AGENTS.md", "CLAUDE.md", ".gitignore", source.name]
    legacy_archive: Path | None = None
    legacy_ledger_digest: str | None = None
    try:
        store.mkdir(parents=True, exist_ok=True)
        if legacy_deg:
            legacy_archive = store / "legacy" / "deg"
            shutil.copytree(source, legacy_archive)
            if (source / "ledger.jsonl").is_file():
                legacy_ledger_digest = digest_file(source / "ledger.jsonl")
        else:
            shutil.copytree(source, store, dirs_exist_ok=True)
        _write_json(store / "manifest.json", manifest_raw)
        _write_json(store / "policy.json", policy_raw)
        _write_json(store / "enrollment.json", enrollment_raw)
        if legacy_deg and (store / "ledger.jsonl").exists():
            (store / "ledger.jsonl").unlink()
        load_policy(load_manifest(store / "manifest.json"))
        with LifecycleTransaction(root, "externalize", paths):
            _restore_previous_hook(root, source)
            shutil.rmtree(source)
            _remove_managed_entry(root / "AGENTS.md", AGENTS_BEGIN, AGENTS_END, remove_empty=True)
            _remove_managed_entry(root / "CLAUDE.md", AGENTS_BEGIN, AGENTS_END, remove_empty=True)
            _remove_managed_entry(root / "AGENTS.md", LEGACY_AGENTS_BEGIN, LEGACY_AGENTS_END, remove_empty=True)
            _remove_managed_entry(root / "CLAUDE.md", LEGACY_AGENTS_BEGIN, LEGACY_AGENTS_END, remove_empty=True)
            _remove_managed_entry(root / ".gitignore", IGNORE_BEGIN, IGNORE_END)
            _remove_managed_entry(root / ".gitignore", LEGACY_IGNORE_BEGIN, LEGACY_IGNORE_END)
            message = "chore: move AG2C governance outside the project"
            commit = _maintenance_commit(root, message, paths)
        registration = register_project(root, project_id=project_id, manifest=store / "manifest.json")
        manifest = load_manifest(store / "manifest.json")
        event = append_event(
            manifest.ledger_path,
            "project-externalized",
            {"project_id": project_id, "commit": commit, "from": "DEG" if legacy_deg else "AG2C"},
        )
        activation = activate_project(root, skill_root=skill_root, harnesses=harnesses)
    except Exception:
        unregister_project(root)
        if store.is_dir():
            shutil.rmtree(store)
        raise
    return {
        "action": "migrated" if legacy_deg else "externalized",
        "project_id": project_id,
        "project_key": registration["key"],
        "root": str(root),
        "store": str(store),
        "version": __version__,
        "commit": commit,
        "legacy_archive": str(legacy_archive) if legacy_archive else None,
        "legacy_ledger_digest": legacy_ledger_digest,
        "ledger_event": event["event_digest"],
        "skill_path": activation["skill_path"],
        "skill_paths": [item["path"] for item in activation["skills"]],
        "working_tree_changed": bool(commit),
        "recovery": {"action": "none"},
    }


def upgrade_project(
    start: Path,
    *,
    skill_root: Path | None = None,
    harnesses: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    root = repository_root(start)
    if root != canonical_worktree(root):
        raise AG2CError(f"upgrade AG2C from the canonical worktree: {canonical_worktree(root)}")
    recovery = recover_lifecycle(root) if (root / ".ag2c").exists() or (root / ".deg").exists() else {"action": "none"}
    if (root / ".deg" / "enrollment.json").is_file() and not (root / ".ag2c" / "enrollment.json").is_file():
        return migrate_project(root, skill_root=skill_root, harnesses=harnesses)
    external = configured_manifest(root)
    if external is not None:
        manifest = load_manifest(external)
        enrollment_path = external.parent / "enrollment.json"
        enrollment = _read_json(enrollment_path)
        enrollment.update({"schema": ENROLLMENT_SCHEMA, "skill": SKILL_NAME, "tool_version": __version__})
        policy = _external_policy(root, _read_json(manifest.policy_path))
        _write_json(enrollment_path, enrollment)
        _write_json(manifest.policy_path, policy)
        registration = register_project(root, project_id=manifest.project_id, manifest=external)
        activation = activate_project(root, skill_root=skill_root, harnesses=harnesses)
        return {
            "action": "reactivated",
            "project_id": manifest.project_id,
            "project_key": registration["key"],
            "root": str(root),
            "store": str(external.parent),
            "version": __version__,
            "commit": None,
            "skill_path": activation["skill_path"],
            "skill_paths": [item["path"] for item in activation["skills"]],
            "working_tree_changed": False,
            "recovery": recovery,
        }
    enrollment_path = root / ".ag2c" / "enrollment.json"
    manifest_path = root / ".ag2c" / "manifest.json"
    policy_path = root / ".ag2c" / "policy.json"
    if not enrollment_path.is_file() or not manifest_path.is_file() or not policy_path.is_file():
        raise AG2CError("project is not enrolled in AG2C")
    return _externalize_project(
        root,
        root / ".ag2c",
        legacy_deg=False,
        skill_root=skill_root,
        harnesses=harnesses,
    )


def migrate_project(
    start: Path,
    *,
    skill_root: Path | None = None,
    harnesses: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    root = repository_root(start)
    if root != canonical_worktree(root):
        raise AG2CError(f"migrate AG2C from the canonical worktree: {canonical_worktree(root)}")
    recovery = recover_lifecycle(root)
    legacy = root / ".deg"
    destination = root / ".ag2c"
    if destination.exists():
        raise AG2CError("cannot migrate because .ag2c already exists")
    required = [legacy / "manifest.json", legacy / "policy.json", legacy / "enrollment.json"]
    if not all(path.is_file() for path in required):
        raise AG2CError("cannot find a complete legacy .deg enrollment")
    return _externalize_project(
        root,
        legacy,
        legacy_deg=True,
        skill_root=skill_root,
        harnesses=harnesses,
    )


def setup_project(
    project: Path | None = None,
    *,
    project_id: str | None = None,
    skill_root: Path | None = None,
    harnesses: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    if project is None:
        skills = install_skills(skill_root, harnesses)
        return {
            "action": "skill-installed",
            "version": __version__,
            "skill_path": skills[0]["path"],
            "skill_paths": [item["path"] for item in skills],
            "skills": skills,
        }
    root = repository_root(project)
    if configured_manifest(root) is not None:
        return upgrade_project(root, skill_root=skill_root, harnesses=harnesses)
    if (root / ".ag2c" / "enrollment.json").is_file():
        return upgrade_project(root, skill_root=skill_root, harnesses=harnesses)
    if (root / ".deg" / "enrollment.json").is_file():
        return migrate_project(root, skill_root=skill_root, harnesses=harnesses)
    result = enroll_project(root, project_id=project_id, skill_root=skill_root, harnesses=harnesses)
    return {"action": "enrolled", "version": __version__, **result}


def repair_project(
    start: Path,
    *,
    skill_root: Path | None = None,
    harnesses: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    root = repository_root(start)
    recovery = recover_lifecycle(root)
    if (root / ".deg" / "enrollment.json").is_file() and not (root / ".ag2c" / "enrollment.json").is_file():
        return migrate_project(root, skill_root=skill_root, harnesses=harnesses)
    activation = activate_project(root, skill_root=skill_root, harnesses=harnesses)
    status = activation_status(root)
    if not status["managed"]:
        raise AG2CError("AG2C repair did not restore management: " + "; ".join(status["issues"]))
    return {"action": "repaired", "root": str(root), "version": __version__, "activation": activation, "recovery": recovery}


def activation_status(start: Path) -> dict[str, Any]:
    root = repository_root(start)
    canonical = canonical_worktree(root)
    issues: list[str] = []
    manifest_path = configured_manifest(canonical)
    if manifest_path is None:
        legacy_manifest = canonical / ".ag2c" / "manifest.json"
        manifest_path = legacy_manifest if legacy_manifest.is_file() else None
    manifest = None
    if manifest_path is not None and manifest_path.is_file():
        try:
            manifest = load_manifest(manifest_path)
        except Exception as exc:
            issues.append(f"AG2C manifest is invalid: {exc}")
    enrollment_path = manifest_path.parent / "enrollment.json" if manifest_path is not None else None
    activation_path = manifest.state_dir / "activation.json" if manifest is not None else None
    if (canonical / ".ag2c").exists() and lifecycle_pending(canonical):
        issues.append("an interrupted AG2C lifecycle transaction needs repair")
    if manifest is None or enrollment_path is None or not enrollment_path.is_file():
        issues.append("project is not enrolled")
    expected_hooks = str((manifest.state_dir / "hooks").resolve()) if manifest is not None else ""
    actual_hooks = str(git(canonical, "config", "--get", "core.hooksPath", check=False)).strip()
    if not expected_hooks or actual_hooks != expected_hooks:
        issues.append("AG2C Git guard is not active")
    activation: dict[str, Any] = {}
    if activation_path is not None and activation_path.is_file():
        activation = json.loads(activation_path.read_text(encoding="utf-8"))
        configured_runtime = activation.get("runtime_command")
        if not isinstance(configured_runtime, list) or not all(isinstance(item, str) for item in configured_runtime):
            configured_runtime = [str(activation.get("python_path", "")), "-m", "ag2c"]
        expected_runtime = _runtime_command()
        configured_executable = Path(configured_runtime[0]) if configured_runtime and configured_runtime[0] else Path()
        if (
            not configured_executable.is_file()
            or configured_executable.resolve() != Path(expected_runtime[0]).resolve()
            or configured_runtime[1:] != expected_runtime[1:]
        ):
            issues.append("AG2C Git guard uses a missing or different runtime")
        installed_skills = activation.get("skills")
        if not isinstance(installed_skills, list) or not installed_skills:
            installed_skills = [{
                "harness": "legacy",
                "path": activation.get("skill_path", ""),
                "digest": activation.get("skill_digest", ""),
            }]
        packaged_digest = skill_digest(skill_source())
        include_harness = len(installed_skills) > 1
        for installed in installed_skills:
            skill = Path(str(installed.get("path", ""))) if isinstance(installed, dict) else Path()
            harness = str(installed.get("harness", "unknown")) if isinstance(installed, dict) else "unknown"
            expected_digest = str(installed.get("digest", "")) if isinstance(installed, dict) else ""
            suffix = f" for {harness}" if include_harness else ""
            if not (skill / "SKILL.md").is_file():
                issues.append(f"AG2C Skill is not installed{suffix}")
            elif skill_digest(skill) != expected_digest:
                issues.append(f"installed AG2C Skill changed after activation{suffix}")
            elif skill_digest(skill) != packaged_digest:
                issues.append(f"installed AG2C Skill is out of date{suffix}")
    else:
        issues.append("AG2C activation record is missing")
    guard = manifest.state_dir / "hooks" / "pre-commit" if manifest is not None else Path()
    if not guard.is_file():
        issues.append("AG2C Git guard hook is missing")
    elif activation and digest_file(guard) != activation.get("guard_digest"):
        issues.append("AG2C Git guard hook changed after activation")
    return {
        "managed": not issues,
        "canonical_root": str(canonical),
        "manifest": str(manifest_path) if manifest_path is not None else None,
        "store": str(manifest_path.parent) if manifest_path is not None else None,
        "issues": issues,
        "activation": activation,
    }


def guard_pre_commit(start: Path) -> int:
    root = repository_root(start)
    canonical = canonical_worktree(root)
    if root == canonical:
        try:
            manifest = load_manifest(discover_manifest(canonical))
            append_event(manifest.ledger_path, "violation-blocked", {"kind": "canonical-commit", "paths": status_entries(root)})
        except Exception:
            pass
        raise AG2CError("AG2C blocks commits in the canonical worktree; use a AG2C task worktree")
    branch = current_branch(root)
    if not branch.startswith("ag2c/"):
        raise AG2CError(f"AG2C blocks commits from an unmanaged worktree branch: {branch}")
    marker_path = git_private_path(root, "ag2c-task.json")
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        task_id = str(marker["task_id"])
        manifest = load_manifest(discover_manifest(canonical))
        task = json.loads((manifest.state_dir / "tasks" / f"{task_id}.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, KeyError, OSError, json.JSONDecodeError) as exc:
        raise AG2CError("AG2C blocks commits without a valid active task record") from exc
    if (
        task.get("state") != "active"
        or task.get("worktree", {}).get("branch") != branch
        or Path(str(task.get("worktree", {}).get("path", ""))).resolve() != root
    ):
        raise AG2CError("AG2C task record does not authorize this worktree commit")
    return 0
