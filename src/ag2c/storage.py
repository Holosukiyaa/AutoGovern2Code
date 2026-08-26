from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import AG2CError
from .gitops import git, repository_root

REGISTRY_SCHEMA = "ag2c.registry.v1"
MANIFEST_CONFIG_KEY = "ag2c.manifest"
PROJECT_KEY_CONFIG_KEY = "ag2c.project-key"
GOVERNANCE_ACTIVE = "active"
GOVERNANCE_STOPPED = "stopped"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def data_root() -> Path:
    configured = os.environ.get("AG2C_DATA_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return (Path(local) / "AutoGovern2Code").resolve()
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return (Path(xdg) / "AutoGovern2Code").expanduser().resolve()
    return (Path.home() / ".local" / "share" / "AutoGovern2Code").resolve()


def registry_path() -> Path:
    return data_root() / "projects.json"


def _path_identity(root: Path) -> str:
    value = str(root.resolve())
    return os.path.normcase(value) if os.name == "nt" else value


def project_key(root: Path) -> str:
    root = root.resolve()
    slug = re.sub(r"[^a-z0-9]+", "-", root.name.lower()).strip("-") or "project"
    digest = hashlib.sha256(_path_identity(root).encode("utf-8")).hexdigest()[:12]
    return f"{slug[:36]}-{digest}"


def project_store(root: Path) -> Path:
    return data_root() / "projects" / project_key(root)


def _read_registry() -> dict[str, Any]:
    path = registry_path()
    if not path.is_file():
        return {"schema": REGISTRY_SCHEMA, "projects": []}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AG2CError(f"cannot read AG2C project registry {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") != REGISTRY_SCHEMA:
        raise AG2CError(f"unsupported AG2C project registry: {path}")
    projects = value.get("projects")
    if not isinstance(projects, list):
        raise AG2CError(f"AG2C project registry has an invalid project list: {path}")
    return value


def _write_registry(value: dict[str, Any]) -> None:
    path = registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def find_project_record(root: Path) -> dict[str, Any] | None:
    root = root.resolve()
    key = project_key(root)
    identity = _path_identity(root)
    for item in _read_registry()["projects"]:
        if not isinstance(item, dict):
            continue
        if item.get("key") == key:
            return dict(item)
        try:
            if _path_identity(Path(str(item.get("root", ".")))) == identity:
                return dict(item)
        except (OSError, TypeError, ValueError):
            continue
    return None


def registered_manifest(root: Path) -> Path | None:
    record = find_project_record(root)
    if record:
        manifest = Path(str(record.get("manifest", "")))
        if manifest.is_file():
            return manifest.resolve()
    candidate = project_store(root) / "manifest.json"
    return candidate.resolve() if candidate.is_file() else None


def register_project(root: Path, *, project_id: str, manifest: Path) -> dict[str, Any]:
    root = root.resolve()
    key = project_key(root)
    registry = _read_registry()
    existing = None
    projects = []
    for item in registry["projects"]:
        if not isinstance(item, dict):
            continue
        same = item.get("key") == key or _path_identity(Path(str(item.get("root", ".")))) == _path_identity(root)
        if same:
            existing = item
            continue
        projects.append(item)
    record = {
        "key": key,
        "project_id": project_id,
        "name": root.name,
        "root": str(root),
        "manifest": str(manifest.resolve()),
        "registered_at": existing.get("registered_at") if isinstance(existing, dict) else _now(),
        "governance": GOVERNANCE_ACTIVE,
    }
    projects.append(record)
    registry["projects"] = sorted(projects, key=lambda item: str(item.get("name", "")).lower())
    _write_registry(registry)
    git(root, "config", "--local", MANIFEST_CONFIG_KEY, str(manifest.resolve()))
    git(root, "config", "--local", PROJECT_KEY_CONFIG_KEY, key)
    return record


def set_project_governance(root: Path, governance: str) -> dict[str, Any]:
    root = repository_root(root)
    if governance not in {GOVERNANCE_ACTIVE, GOVERNANCE_STOPPED}:
        raise AG2CError(f"unsupported governance state: {governance}")
    key = project_key(root)
    registry = _read_registry()
    updated = None
    projects = []
    for item in registry["projects"]:
        if not isinstance(item, dict):
            continue
        same = item.get("key") == key or _path_identity(Path(str(item.get("root", ".")))) == _path_identity(root)
        if same:
            updated = dict(item)
            updated["governance"] = governance
            updated["root"] = str(root)
            projects.append(updated)
        else:
            projects.append(item)
    if updated is None:
        raise AG2CError(f"project is not in the AG2C registry: {root}")
    registry["projects"] = projects
    _write_registry(registry)
    return updated


def unregister_project(root: Path, *, remove_data: bool = False) -> dict[str, Any]:
    root = repository_root(root)
    key = project_key(root)
    record = find_project_record(root)
    manifest = configured_manifest(root)
    if manifest is None and record and record.get("manifest"):
        candidate = Path(str(record["manifest"]))
        if candidate.is_file():
            manifest = candidate.resolve()
    registry = _read_registry()
    before = len(registry["projects"])
    registry["projects"] = [
        item for item in registry["projects"]
        if not isinstance(item, dict) or (item.get("key") != key and _path_identity(Path(str(item.get("root", ".")))) != _path_identity(root))
    ]
    if len(registry["projects"]) != before:
        _write_registry(registry)
    git(root, "config", "--local", "--unset-all", MANIFEST_CONFIG_KEY, check=False)
    git(root, "config", "--local", "--unset-all", PROJECT_KEY_CONFIG_KEY, check=False)
    removed_data = False
    if remove_data:
        expected = project_store(root).resolve()
        store = manifest.parent.resolve() if manifest is not None else expected
        if store == expected and store.is_dir():
            shutil.rmtree(store)
            removed_data = True
    return {"root": str(root), "key": key, "registered": False, "data_removed": removed_data}


def configured_manifest(start: Path) -> Path | None:
    try:
        root = repository_root(start)
    except AG2CError:
        return None
    value = str(git(root, "config", "--local", "--get", MANIFEST_CONFIG_KEY, check=False)).strip()
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = (root / path).resolve()
    return path.resolve()


def project_records() -> list[dict[str, Any]]:
    registry = _read_registry()
    records: list[dict[str, Any]] = []
    for item in registry["projects"]:
        if not isinstance(item, dict):
            continue
        record = dict(item)
        root = Path(str(record.get("root", "")))
        manifest = Path(str(record.get("manifest", "")))
        record["root_exists"] = root.is_dir()
        record["manifest_exists"] = manifest.is_file()
        records.append(record)
    return records


def git_private_path(root: Path, name: str) -> Path:
    value = str(git(root, "rev-parse", "--git-path", name)).strip()
    path = Path(value)
    return path.resolve() if path.is_absolute() else (root / path).resolve()
