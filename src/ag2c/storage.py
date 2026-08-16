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


def register_project(root: Path, *, project_id: str, manifest: Path) -> dict[str, Any]:
    root = root.resolve()
    key = project_key(root)
    registry = _read_registry()
    projects = [
        item
        for item in registry["projects"]
        if isinstance(item, dict) and item.get("key") != key and _path_identity(Path(str(item.get("root", ".")))) != _path_identity(root)
    ]
    record = {
        "key": key,
        "project_id": project_id,
        "name": root.name,
        "root": str(root),
        "manifest": str(manifest.resolve()),
        "registered_at": _now(),
    }
    projects.append(record)
    registry["projects"] = sorted(projects, key=lambda item: str(item.get("name", "")).lower())
    _write_registry(registry)
    git(root, "config", "--local", MANIFEST_CONFIG_KEY, str(manifest.resolve()))
    git(root, "config", "--local", PROJECT_KEY_CONFIG_KEY, key)
    return record


def unregister_project(root: Path, *, remove_data: bool = False) -> dict[str, Any]:
    root = repository_root(root)
    key = project_key(root)
    manifest = configured_manifest(root)
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
    if remove_data and manifest is not None:
        store = manifest.parent.resolve()
        expected = project_store(root).resolve()
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
