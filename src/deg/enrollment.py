from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import MANIFEST_SCHEMA, POLICY_SCHEMA, load_manifest, load_policy
from .errors import DEGError
from .gitops import canonical_worktree, current_branch, git, repository_root, status_entries
from .index import build_index
from .ledger import append_event
from .util import digest_file

ENROLLMENT_SCHEMA = "deg.enrollment.v1"
ACTIVATION_SCHEMA = "deg.activation.v1"
SKILL_NAME = "deg-governed-development"
AGENTS_BEGIN = "<!-- DEG:BEGIN -->"
AGENTS_END = "<!-- DEG:END -->"
IGNORE_BEGIN = "# DEG:BEGIN"
IGNORE_END = "# DEG:END"

AGENTS_BLOCK = f"""{AGENTS_BEGIN}
# DEG governed engineering

This repository is enrolled in DEG. For every request that may change source,
tests, documentation, configuration, dependencies, or generated deliverables:

1. Use `${SKILL_NAME}` before the first write.
2. Do not edit this canonical checkout.
3. Start a DEG task and edit only the returned external Git worktree.
4. Run DEG verification after the final change.
5. Finish through DEG so verified commits are fast-forwarded into this checkout.

Do not claim completion without a valid DEG task record and verification evidence.
If DEG blocks an action, fix the cause; never bypass the guard, checker, or ledger.
{AGENTS_END}
"""

IGNORE_BLOCK = f"""{IGNORE_BEGIN}
.deg/state/
.deg/ledger.jsonl
.deg/ledger.jsonl.lock
{IGNORE_END}
"""

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _project_id(root: Path) -> str:
    value = re.sub(r"[^a-z0-9._-]+", "-", root.name.lower()).strip("-.")
    return value or "project"


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
            raise DEGError(f"cannot update malformed DEG block in {path}")
        finish += len(end)
        prefix = original[:start].rstrip("\r\n")
        separator = newline * 2 if prefix else ""
        content = prefix + separator + rendered + original[finish:]
    else:
        content = original.rstrip("\r\n") + (newline * 2 if original.strip() else "") + rendered + newline
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(content)


def _tracked_roots(root: Path) -> list[str]:
    tracked = [line.replace("\\", "/") for line in str(git(root, "ls-files")).splitlines()]
    candidates: dict[str, bool] = {}
    for relative in tracked:
        if relative in {"AGENTS.md", ".gitignore"} or relative.startswith(".deg/"):
            continue
        first, separator, _ = relative.partition("/")
        candidates[first] = bool(separator) or (root / first).is_dir()
    if not candidates:
        for child in sorted(root.iterdir(), key=lambda item: item.name):
            if child.name not in {".git", ".deg", ".gitignore", "AGENTS.md"}:
                candidates[child.name] = child.is_dir()
    if not candidates:
        raise DEGError("cannot enroll an empty project; add the initial project files first")
    return sorted(candidates)


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
            checkers.append(
                {"id": "check.node", "stage": "floor", "target": "app", "command": ["npm", "test"], "cwd": ".", "timeout": 900}
            )
    if (root / "tests").is_dir() and any(root.glob("**/test*.py")):
        pyproject = root / "pyproject.toml"
        uses_pytest = (
            (root / "pytest.ini").is_file()
            or (root / "conftest.py").is_file()
            or (pyproject.is_file() and "pytest" in pyproject.read_text(encoding="utf-8", errors="ignore"))
        )
        command = (
            ["python", "-m", "pytest"]
            if uses_pytest
            else ["python", "-m", "unittest", "discover", "-s", "tests"]
        )
        checkers.append(
            {"id": "check.python", "stage": "floor", "target": "app", "command": command, "cwd": ".", "timeout": 900}
        )
    return checkers


def _skill_source() -> Path:
    source = Path(__file__).with_name("skills") / SKILL_NAME
    if not (source / "SKILL.md").is_file():
        raise DEGError("packaged DEG Skill is missing")
    return source


def _skill_digest(path: Path) -> str:
    digest = hashlib.sha256()
    for file in sorted((item for item in path.rglob("*") if item.is_file()), key=lambda item: item.as_posix()):
        digest.update(file.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(file.read_bytes())
    return digest.hexdigest()


def install_skill(destination_root: Path | None = None) -> Path:
    if destination_root is None:
        configured = os.environ.get("CODEX_HOME")
        destination_root = Path(configured) if configured else Path.home() / ".codex"
        destination_root = destination_root / "skills"
    destination = destination_root.resolve() / SKILL_NAME
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        raise DEGError(f"refusing to replace a symlinked Skill directory: {destination}")
    if destination.exists() and not destination.is_dir():
        raise DEGError(f"refusing to replace a non-directory Skill path: {destination}")
    staging = destination.parent / f".{SKILL_NAME}-{secrets.token_hex(4)}.tmp"
    backup = destination.parent / f".{SKILL_NAME}-{secrets.token_hex(4)}.backup"
    replaced = False
    installed = False
    try:
        shutil.copytree(_skill_source(), staging)
        if destination.exists():
            os.replace(destination, backup)
            replaced = True
        os.replace(staging, destination)
        installed = True
    except Exception:
        if replaced and not destination.exists() and backup.exists():
            os.replace(backup, destination)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)
        if installed and backup.exists():
            shutil.rmtree(backup)
    return destination


def _activation_path(canonical: Path) -> Path:
    return canonical / ".deg" / "state" / "activation.json"


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def activate_project(start: Path, *, skill_root: Path | None = None) -> dict[str, Any]:
    root = repository_root(start)
    canonical = canonical_worktree(root)
    if root != canonical:
        raise DEGError(f"activate DEG from the canonical worktree: {canonical}")
    enrollment_path = canonical / ".deg" / "enrollment.json"
    if not enrollment_path.is_file():
        raise DEGError("project is not enrolled in DEG")
    previous = str(git(canonical, "config", "--get", "core.hooksPath", check=False)).strip()
    hooks = (canonical / ".deg" / "state" / "hooks").resolve()
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
    script = f"#!/bin/sh\n{_shell_quote(Path(sys.executable).resolve().as_posix())} -m deg guard pre-commit || exit $?\n"
    if delegate is not None:
        script += f"{_shell_quote(delegate.as_posix())} \"$@\"\n"
    hook.write_text(script, encoding="utf-8", newline="\n")
    try:
        hook.chmod(0o755)
    except OSError:
        pass
    skill_path = install_skill(skill_root)
    git(canonical, "config", "core.hooksPath", expected)
    activation = {
        "schema": ACTIVATION_SCHEMA,
        "activated_at": _now(),
        "canonical_root": str(canonical),
        "python_path": str(Path(sys.executable).resolve()),
        "previous_hooks_path": previous,
        "guard_digest": digest_file(hook),
        "skill_path": str(skill_path),
        "skill_digest": _skill_digest(skill_path),
    }
    _write_json(activation_path, activation)
    manifest = load_manifest(canonical / ".deg" / "manifest.json")
    policy = load_policy(manifest)
    build_index(manifest, policy)
    append_event(manifest.ledger_path, "project-activated", {"canonical_root": str(canonical), "skill_digest": activation["skill_digest"]})
    return activation


def enroll_project(start: Path, *, project_id: str | None = None, skill_root: Path | None = None) -> dict[str, Any]:
    root = repository_root(start)
    if root != canonical_worktree(root):
        raise DEGError("enroll DEG from the canonical worktree")
    dirty = status_entries(root)
    if dirty:
        raise DEGError("enrollment requires a clean worktree; commit or stash: " + ", ".join(dirty))
    if (root / ".deg" / "enrollment.json").exists():
        raise DEGError("project is already enrolled; run `deg activate`")
    project_id = project_id or _project_id(root)
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", project_id):
        raise DEGError("project id must contain only lowercase letters, digits, dots, underscores, and hyphens")
    project_roots = _tracked_roots(root)
    checkers = _native_checkers(root)
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "project": {"id": project_id},
        "policy": ".deg/policy.json",
        "state_dir": ".deg/state",
        "ledger": ".deg/ledger.jsonl",
        "targets": [
            {
                "id": "app",
                "path": ".",
                "governed_roots": ["."],
                "exclude": [".deg/state/**", ".deg/ledger.jsonl", ".deg/ledger.jsonl.lock"],
            }
        ],
    }
    checker_ids = [item["id"] for item in checkers]
    policy = {
        "schema": POLICY_SCHEMA,
        "cards": [
            {
                "id": "constitution.project",
                "type": "constitution",
                "title": "Managed project invariants",
                "summary": "All changes use DEG routing, isolated worktrees, verified checks, and evidence-backed integration.",
                "references": ["AGENTS.md"],
            },
            {
                "id": "floor.project",
                "type": "floor",
                "title": "Project implementation",
                "summary": "Primary responsibility for every file present when the project was enrolled.",
                "scopes": [
                    {
                        "target": "app",
                        "include": ["**"],
                        "ownership": "primary",
                    }
                ],
                "checkers": checker_ids,
                "references": ["AGENTS.md"],
            },
        ],
        "relations": [],
        "contracts": [],
        "checkers": checkers,
    }
    enrollment = {"schema": ENROLLMENT_SCHEMA, "project_id": project_id, "enrolled_at": _now(), "skill": SKILL_NAME}
    _write_json(root / ".deg" / "manifest.json", manifest)
    _write_json(root / ".deg" / "policy.json", policy)
    _write_json(root / ".deg" / "enrollment.json", enrollment)
    _replace_block(root / "AGENTS.md", AGENTS_BEGIN, AGENTS_END, AGENTS_BLOCK)
    _replace_block(root / ".gitignore", IGNORE_BEGIN, IGNORE_END, IGNORE_BLOCK)
    git(root, "add", "AGENTS.md", ".gitignore", ".deg/enrollment.json", ".deg/manifest.json", ".deg/policy.json")
    git(root, "commit", "-m", "chore: enroll project in DEG")
    loaded_manifest = load_manifest(root / ".deg" / "manifest.json")
    event = append_event(
        loaded_manifest.ledger_path,
        "project-enrolled",
        {"project_id": project_id, "commit": str(git(root, "rev-parse", "HEAD")).strip(), "governed_roots": project_roots},
    )
    activation = activate_project(root, skill_root=skill_root)
    return {"project_id": project_id, "root": str(root), "skill_path": activation["skill_path"], "ledger_event": event["event_digest"]}


def activation_status(start: Path) -> dict[str, Any]:
    root = repository_root(start)
    canonical = canonical_worktree(root)
    manifest_path = canonical / ".deg" / "manifest.json"
    enrollment_path = canonical / ".deg" / "enrollment.json"
    activation_path = _activation_path(canonical)
    issues: list[str] = []
    if not enrollment_path.is_file() or not manifest_path.is_file():
        issues.append("project is not enrolled")
    expected_hooks = str((canonical / ".deg" / "state" / "hooks").resolve())
    actual_hooks = str(git(canonical, "config", "--get", "core.hooksPath", check=False)).strip()
    if actual_hooks != expected_hooks:
        issues.append("DEG Git guard is not active")
    activation: dict[str, Any] = {}
    if activation_path.is_file():
        activation = json.loads(activation_path.read_text(encoding="utf-8"))
        configured_python = Path(str(activation.get("python_path", "")))
        if not configured_python.is_file() or configured_python.resolve() != Path(sys.executable).resolve():
            issues.append("DEG Git guard uses a missing or different Python interpreter")
        skill = Path(str(activation.get("skill_path", "")))
        if not (skill / "SKILL.md").is_file():
            issues.append("DEG Skill is not installed")
        elif _skill_digest(skill) != activation.get("skill_digest"):
            issues.append("installed DEG Skill changed after activation")
        elif _skill_digest(skill) != _skill_digest(_skill_source()):
            issues.append("installed DEG Skill is out of date")
    else:
        issues.append("DEG activation record is missing")
    guard = canonical / ".deg" / "state" / "hooks" / "pre-commit"
    if not guard.is_file():
        issues.append("DEG Git guard hook is missing")
    elif activation and digest_file(guard) != activation.get("guard_digest"):
        issues.append("DEG Git guard hook changed after activation")
    return {"managed": not issues, "canonical_root": str(canonical), "issues": issues, "activation": activation}


def guard_pre_commit(start: Path) -> int:
    root = repository_root(start)
    canonical = canonical_worktree(root)
    if root == canonical:
        try:
            manifest = load_manifest(canonical / ".deg" / "manifest.json")
            append_event(manifest.ledger_path, "violation-blocked", {"kind": "canonical-commit", "paths": status_entries(root)})
        except Exception:
            pass
        raise DEGError("DEG blocks commits in the canonical worktree; use a DEG task worktree")
    branch = current_branch(root)
    if not branch.startswith("deg/"):
        raise DEGError(f"DEG blocks commits from an unmanaged worktree branch: {branch}")
    marker_path = root / ".deg" / "state" / "active-task.json"
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        task_id = str(marker["task_id"])
        task = json.loads((canonical / ".deg" / "state" / "tasks" / f"{task_id}.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, KeyError, OSError, json.JSONDecodeError) as exc:
        raise DEGError("DEG blocks commits without a valid active task record") from exc
    if (
        task.get("state") != "active"
        or task.get("worktree", {}).get("branch") != branch
        or Path(str(task.get("worktree", {}).get("path", ""))).resolve() != root
    ):
        raise DEGError("DEG task record does not authorize this worktree commit")
    return 0
