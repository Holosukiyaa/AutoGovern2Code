"""Extracted by flatten-split."""
from __future__ import annotations
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any
from . import __version__
from .config import MANIFEST_SCHEMA, POLICY_SCHEMA, discover_manifest, load_manifest, load_policy
from .errors import AG2CError, RELOCATED_PROJECT, STALE_EXTERNAL_STORE
from .gitops import canonical_worktree, current_branch, git, repository_root, seize_existing_git, status_entries
from .harnesses import SKILL_NAME, install_skills
from .index import build_index
from .lifecycle import LifecycleTransaction, recover_lifecycle
from .ledger import append_event
from .storage import BINDING_HEALTHY, BINDING_RELOCATED, BINDING_STALE, clear_stale_git_enrollment, configured_manifest, git_private_path, project_store, register_project, registered_manifest, resolve_enrollment_binding, unregister_project
from .util import digest_file
from .enrollment import ACTIVATION_SCHEMA, AGENTS_BEGIN, AGENTS_END, ENROLLMENT_SCHEMA, IGNORE_BEGIN, IGNORE_END, LEGACY_AGENTS_BEGIN, LEGACY_AGENTS_END, LEGACY_IGNORE_BEGIN, LEGACY_IGNORE_END, _activation_path, _active_task_ids, _enrollment_file, _external_manifest, _external_policy, _first_drill_step, _install_guard_hooks, _maintenance_commit, _native_checkers, _now, _previous_hooks_directory, _project_id, _read_json, _remove_managed_entry, _replace_legacy_namespace, _repoint_manifest_root, _restore_previous_hook, _runtime_command, _tracked_roots, _upgrade_python_checkers, _write_json, activation_status

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
    hooks = (manifest.state_dir / "hooks").resolve()
    expected = str(hooks)
    activation_path = _activation_path(canonical)
    old_activation: dict[str, Any] = {}
    if activation_path.is_file():
        old_activation = json.loads(activation_path.read_text(encoding="utf-8"))
    previous, previous_dir = _previous_hooks_directory(canonical, expected, old_activation)
    runtime_command = _runtime_command()
    hook, delegated_hooks = _install_guard_hooks(hooks, previous_dir, runtime_command)
    try:
        seize_existing_git(canonical)
    except AG2CError:
        pass
    skills = install_skills(skill_root, harnesses)
    mcp = []
    try:
        from .mcp_server import install_mcp_clients

        mcp = install_mcp_clients()
    except OSError:
        mcp = []
    primary_skill = skills[0]
    git(canonical, "config", "core.hooksPath", expected)
    activation = {
        "schema": ACTIVATION_SCHEMA,
        "activated_at": _now(),
        "canonical_root": str(canonical),
        "python_path": str(Path(sys.executable).resolve()),
        "runtime_command": runtime_command,
        "previous_hooks_path": previous,
        "delegated_hooks": delegated_hooks,
        "guard_digest": digest_file(hook),
        "skill_path": primary_skill["path"],
        "skill_digest": primary_skill["digest"],
        "skills": skills,
        "mcp": mcp,
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

def recover_relocated_enrollment(
    start: Path,
    binding: dict[str, Any] | None = None,
    *,
    skill_root: Path | None = None,
    harnesses: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    root = repository_root(start)
    binding = binding or resolve_enrollment_binding(root)
    if binding.get("state") != BINDING_RELOCATED or not binding.get("manifest"):
        raise AG2CError("project does not have a relocated AG2C store to rebind")
    manifest_path = Path(str(binding["manifest"]))
    _repoint_manifest_root(manifest_path, root)
    loaded = load_manifest(manifest_path, project_root=root)
    registration = register_project(
        root,
        project_id=loaded.project_id,
        manifest=manifest_path,
        key=str(binding.get("project_key") or ""),
    )
    activation = activate_project(root, skill_root=skill_root, harnesses=harnesses)
    return {
        "action": "rebound",
        "project_id": loaded.project_id,
        "project_key": registration["key"],
        "root": str(root),
        "store": str(manifest_path.parent),
        "working_tree_changed": False,
        "skill_path": activation["skill_path"],
        "skill_paths": [item["path"] for item in activation["skills"]],
        "recovery": {
            "action": "rebound",
            "code": RELOCATED_PROJECT,
            "history_recovered": True,
            "previous_manifest": str(binding.get("configured_manifest") or ""),
            "previous_key": str(binding.get("configured_key") or ""),
        },
    }

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
    recovery: dict[str, Any] = {"action": "none"}
    binding = resolve_enrollment_binding(root)
    if binding["state"] == BINDING_HEALTHY:
        raise AG2CError("project is already enrolled; run `ag2c upgrade`")
    if binding["state"] == BINDING_RELOCATED:
        return recover_relocated_enrollment(root, binding, skill_root=skill_root, harnesses=harnesses)
    if (root / ".ag2c" / "enrollment.json").exists() or (root / ".deg" / "enrollment.json").exists():
        raise AG2CError("project contains a legacy enrollment; run `ag2c upgrade`")
    if binding["state"] == BINDING_STALE:
        clear_stale_git_enrollment(root)
        recovery = {
            "action": "reenrolled",
            "code": STALE_EXTERNAL_STORE,
            "history_recovered": False,
            "previous_manifest": str(binding.get("configured_manifest") or ""),
            "previous_key": str(binding.get("configured_key") or ""),
        }
    project_id = project_id or _project_id(root)
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", project_id):
        raise AG2CError("project id must contain only lowercase letters, digits, dots, underscores, and hyphens")
    project_roots = _tracked_roots(root)
    checkers = _native_checkers(root)
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "project": {"id": project_id, "root": str(root), "trunk": current_branch(root)},
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
    from .govern import compose_baseline_governance, finalize_ingest

    ingested = compose_baseline_governance(root, project_roots, checker_ids)
    policy = {
        "schema": POLICY_SCHEMA,
        "coverage": {
            "level": "baseline",
            "strategy": "conservative",
            "managed_by": "ag2c",
            "areas": project_roots,
        },
        "cards": ingested["cards"],
        "relations": ingested["relations"],
        "contracts": ingested["contracts"],
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
        finalize_ingest(loaded_manifest, actor="ag2c", reason="initial enrollment")
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
        "next_step": _first_drill_step(),
    }

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

def align_engine(
    start: Path,
    *,
    skill_root: Path | None = None,
    harnesses: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    root = repository_root(start)
    if root != canonical_worktree(root):
        raise AG2CError(f"align AG2C from the canonical worktree: {canonical_worktree(root)}")
    enrollment_path = _enrollment_file(root)
    if enrollment_path is None:
        raise AG2CError("project is not enrolled in AG2C")
    enrollment = _read_json(enrollment_path)
    from_version = str(enrollment.get("tool_version") or "")
    policy_path = enrollment_path.parent / "policy.json"
    policy_changed = False
    if policy_path.is_file():
        policy = _read_json(policy_path)
        policy_changed = _upgrade_python_checkers(policy)
        if policy_changed:
            _write_json(policy_path, policy)
    activation = activate_project(root, skill_root=skill_root, harnesses=harnesses)
    enrollment.update(
        {
            "schema": ENROLLMENT_SCHEMA,
            "skill": SKILL_NAME,
            "tool_version": __version__,
            "aligned_at": _now(),
        }
    )
    _write_json(enrollment_path, enrollment)
    action = "current" if from_version == __version__ and not policy_changed else "aligned"
    event_digest = None
    if action == "aligned":
        manifest = load_manifest(enrollment_path.parent / "manifest.json")
        event = append_event(
            manifest.ledger_path,
            "engine-aligned",
            {
                "from_version": from_version or "unknown",
                "to_version": __version__,
                "resliced": False,
            },
        )
        event_digest = event["event_digest"]
    return {
        "action": action,
        "root": str(root),
        "name": root.name,
        "from_version": from_version or "unknown",
        "to_version": __version__,
        "resliced": False,
        "policy_migrated": policy_changed,
        "skill_path": activation["skill_path"],
        "ledger_event": event_digest,
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
    binding = resolve_enrollment_binding(root)
    if binding["state"] == BINDING_RELOCATED:
        rebound = recover_relocated_enrollment(root, binding, skill_root=skill_root, harnesses=harnesses)
        rebound["version"] = __version__
        rebound["commit"] = None
        return rebound
    if binding["state"] == BINDING_STALE:
        result = enroll_project(root, skill_root=skill_root, harnesses=harnesses)
        return {"action": "reenrolled", "version": __version__, "commit": None, **result}
    external = configured_manifest(root)
    if external is not None and external.is_file():
        manifest = load_manifest(external)
        enrollment_path = external.parent / "enrollment.json"
        enrollment = _read_json(enrollment_path)
        enrollment.update({"schema": ENROLLMENT_SCHEMA, "skill": SKILL_NAME, "tool_version": __version__})
        policy = _external_policy(root, _read_json(manifest.policy_path))
        _write_json(enrollment_path, enrollment)
        _write_json(manifest.policy_path, policy)
        registration = register_project(root, project_id=manifest.project_id, manifest=external)
        activation = activate_project(root, skill_root=skill_root, harnesses=harnesses)
        from .govern import finalize_ingest

        finalize_ingest(manifest, actor="ag2c", reason="upgrade ingest")
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
        mcp = []
        try:
            from .mcp_server import install_mcp_clients

            mcp = install_mcp_clients()
        except OSError:
            mcp = []
        return {
            "action": "skill-installed",
            "version": __version__,
            "skill_path": skills[0]["path"],
            "skill_paths": [item["path"] for item in skills],
            "skills": skills,
            "mcp": mcp,
        }
    root = repository_root(project)
    binding = resolve_enrollment_binding(root)
    if binding["state"] == BINDING_STALE:
        result = enroll_project(root, project_id=project_id, skill_root=skill_root, harnesses=harnesses)
        return {"action": "enrolled", "version": __version__, **result}
    if binding["state"] in {BINDING_HEALTHY, BINDING_RELOCATED}:
        return upgrade_project(root, skill_root=skill_root, harnesses=harnesses)
    stored = registered_manifest(root)
    if stored is not None:
        register_project(root, project_id=load_manifest(stored, project_root=root).project_id, manifest=stored)
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
    binding = resolve_enrollment_binding(root)
    if binding["state"] == BINDING_STALE:
        recovered = enroll_project(root, skill_root=skill_root, harnesses=harnesses)
        recovery = recovered.get("recovery") or recovery
    elif binding["state"] == BINDING_RELOCATED:
        recovered = recover_relocated_enrollment(root, binding, skill_root=skill_root, harnesses=harnesses)
        recovery = recovered.get("recovery") or recovery
    aligned = align_engine(root, skill_root=skill_root, harnesses=harnesses)
    mcp = []
    try:
        from .mcp_server import install_mcp_clients

        mcp = install_mcp_clients()
    except OSError:
        mcp = []
    status = activation_status(root)
    if not status["managed"]:
        raise AG2CError("AG2C repair did not restore management: " + "; ".join(status["issues"]))
    return {
        "action": "repaired",
        "root": str(root),
        "version": __version__,
        "activation": status.get("activation") or {},
        "recovery": recovery,
        "alignment": aligned,
        "mcp": mcp,
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
        raise AG2CError(
            "AG2C blocks commits in the canonical worktree; use an AG2C task worktree. "
            "Connect the AG2C MCP once (`ag2c mcp install`) and call ag2c_task_start."
        )
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
        raise AG2CError("AG2C blocks commits without a valid open task record") from exc
    if (
        task.get("state") not in {"active", "verified"}
        or task.get("worktree", {}).get("branch") != branch
        or Path(str(task.get("worktree", {}).get("path", ""))).resolve() != root
    ):
        raise AG2CError("AG2C task record does not authorize this worktree commit")
    return 0
