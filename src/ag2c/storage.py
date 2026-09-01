from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import AG2CError, RELOCATED_PROJECT, STALE_EXTERNAL_STORE
from .gitops import git, repository_root

REGISTRY_SCHEMA = "ag2c.registry.v1"
MANIFEST_CONFIG_KEY = "ag2c.manifest"
PROJECT_KEY_CONFIG_KEY = "ag2c.project-key"
HOOKS_PATH_CONFIG_KEY = "core.hooksPath"
GOVERNANCE_ACTIVE = "active"
GOVERNANCE_STOPPED = "stopped"
BINDING_UNBOUND = "unbound"
BINDING_HEALTHY = "healthy"
BINDING_RELOCATED = "relocated"
BINDING_STALE = "stale"
_UNCHANGED = object()
_STORE_MARKER = "/autogovern2code/projects/"


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


def project_store(root: Path, key: str | None = None) -> Path:
    return data_root() / "projects" / (key or project_key(root))


def store_dir_for_key(key: str) -> Path:
    return data_root() / "projects" / key


def _posix_path(value: Path | str) -> str:
    return str(value).replace("\\", "/")


def looks_like_ag2c_store_path(value: Path | str) -> bool:
    return _STORE_MARKER in _posix_path(value).lower()


def looks_like_ag2c_hooks_path(value: Path | str) -> bool:
    text = _posix_path(value).lower().rstrip("/")
    return looks_like_ag2c_store_path(text) and text.endswith("/state/hooks")


def relocated_manifest_candidate(path: Path) -> Path | None:
    text = _posix_path(path)
    index = text.lower().find(_STORE_MARKER)
    if index < 0:
        return None
    suffix = text[index + len(_STORE_MARKER) :]
    if not suffix:
        return None
    return (data_root() / "projects" / Path(suffix)).resolve()


def _git_config_get(root: Path, key: str) -> str:
    return str(git(root, "config", "--local", "--get", key, check=False)).strip()


def _git_config_list(root: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in str(git(root, "config", "--list", check=False)).splitlines():
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value
    return values


def _git_config_lookup(values: dict[str, str], key: str) -> str:
    if key in values:
        return values[key]
    lowered = key.lower()
    for name, value in values.items():
        if name.lower() == lowered:
            return value
    return ""


def _configured_manifest_from_value(root: Path, value: str) -> Path | None:
    text = (value or "").strip()
    if not text:
        return None
    path = Path(text)
    if not path.is_absolute():
        path = (root / path).resolve()
    return path.resolve()


def _git_config_set(root: Path, key: str, value: str | None) -> None:
    if value:
        git(root, "config", "--local", key, value)
        return
    git(root, "config", "--local", "--unset-all", key, check=False)


def apply_git_enrollment(
    root: Path,
    *,
    manifest: Path | None,
    key: str | None,
    hooks_path: str | None | object = _UNCHANGED,
) -> None:
    root = repository_root(root)
    previous = {
        "manifest": _git_config_get(root, MANIFEST_CONFIG_KEY),
        "key": _git_config_get(root, PROJECT_KEY_CONFIG_KEY),
        "hooks": str(git(root, "config", "--get", HOOKS_PATH_CONFIG_KEY, check=False)).strip(),
    }
    try:
        _git_config_set(root, MANIFEST_CONFIG_KEY, str(manifest.resolve()) if manifest is not None else None)
        _git_config_set(root, PROJECT_KEY_CONFIG_KEY, key or None)
        if hooks_path is _UNCHANGED:
            return
        next_hooks = str(hooks_path) if hooks_path else ""
        if next_hooks:
            git(root, "config", "--local", HOOKS_PATH_CONFIG_KEY, next_hooks)
        elif looks_like_ag2c_hooks_path(previous["hooks"]):
            git(root, "config", "--local", "--unset-all", HOOKS_PATH_CONFIG_KEY, check=False)
    except Exception:
        _git_config_set(root, MANIFEST_CONFIG_KEY, previous["manifest"] or None)
        _git_config_set(root, PROJECT_KEY_CONFIG_KEY, previous["key"] or None)
        if previous["hooks"]:
            git(root, "config", "--local", HOOKS_PATH_CONFIG_KEY, previous["hooks"])
        elif hooks_path is not _UNCHANGED:
            git(root, "config", "--local", "--unset-all", HOOKS_PATH_CONFIG_KEY, check=False)
        raise


def clear_stale_git_enrollment(root: Path) -> None:
    apply_git_enrollment(root, manifest=None, key=None, hooks_path=None)


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


def register_project(root: Path, *, project_id: str, manifest: Path, key: str | None = None) -> dict[str, Any]:
    root = root.resolve()
    path_key = project_key(root)
    key = key or path_key
    registry = _read_registry()
    existing = None
    projects = []
    for item in registry["projects"]:
        if not isinstance(item, dict):
            continue
        same = (
            item.get("key") == key
            or item.get("key") == path_key
            or _path_identity(Path(str(item.get("root", ".")))) == _path_identity(root)
        )
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
    apply_git_enrollment(root, manifest=manifest, key=key)
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
    apply_git_enrollment(root, manifest=None, key=None, hooks_path=None)
    removed_data = False
    if remove_data:
        keys = {key}
        if record and record.get("key"):
            keys.add(str(record["key"]))
        expected_stores = {(data_root() / "projects" / item).resolve() for item in keys if item}
        store = manifest.parent.resolve() if manifest is not None else project_store(root).resolve()
        if store in expected_stores and store.is_dir():
            shutil.rmtree(store)
            removed_data = True
    return {"root": str(root), "key": key, "registered": False, "data_removed": removed_data}


def configured_manifest(start: Path, *, root: Path | None = None) -> Path | None:
    try:
        resolved = root if root is not None else repository_root(start)
    except AG2CError:
        return None
    return _configured_manifest_from_value(resolved, _git_config_get(resolved, MANIFEST_CONFIG_KEY))


def configured_project_key(start: Path, *, root: Path | None = None) -> str:
    try:
        resolved = root if root is not None else repository_root(start)
    except AG2CError:
        return ""
    return _git_config_get(resolved, PROJECT_KEY_CONFIG_KEY)


def configured_hooks_path(start: Path, *, root: Path | None = None) -> str:
    try:
        resolved = root if root is not None else repository_root(start)
    except AG2CError:
        return ""
    return str(git(resolved, "config", "--get", HOOKS_PATH_CONFIG_KEY, check=False)).strip()


def _empty_binding(root: Path | None = None) -> dict[str, Any]:
    return {
        "state": BINDING_UNBOUND,
        "code": None,
        "root": str(root) if root is not None else "",
        "configured_manifest": "",
        "configured_key": "",
        "configured_hooks": "",
        "manifest": None,
        "store": None,
        "project_key": project_key(root) if root is not None else "",
        "history_recoverable": False,
    }


def resolve_enrollment_binding(start: Path, *, root: Path | None = None) -> dict[str, Any]:
    try:
        repo = root if root is not None else repository_root(start)
    except AG2CError:
        return _empty_binding()
    config = _git_config_list(repo)
    configured = _configured_manifest_from_value(repo, _git_config_lookup(config, MANIFEST_CONFIG_KEY))
    key = _git_config_lookup(config, PROJECT_KEY_CONFIG_KEY)
    hooks = _git_config_lookup(config, HOOKS_PATH_CONFIG_KEY)
    derived = project_store(repo) / "manifest.json"
    if configured is not None and configured.is_file():
        return {
            "state": BINDING_HEALTHY,
            "code": None,
            "root": str(repo),
            "configured_manifest": str(configured),
            "configured_key": key,
            "configured_hooks": hooks,
            "manifest": str(configured),
            "store": str(configured.parent),
            "project_key": key or project_key(repo),
            "history_recoverable": True,
        }
    found: list[tuple[str, Path]] = []
    seen: set[Path] = set()

    def _add(candidate_key: str, manifest: Path) -> None:
        resolved = manifest.resolve()
        if not resolved.is_file() or resolved in seen:
            return
        seen.add(resolved)
        found.append((candidate_key or resolved.parent.name, resolved))

    if key:
        _add(key, store_dir_for_key(key) / "manifest.json")
    if configured is not None:
        rewritten = relocated_manifest_candidate(configured)
        if rewritten is not None:
            _add(key or rewritten.parent.name, rewritten)
    if derived.is_file():
        _add(project_key(repo), derived)
    if found:
        use_key, manifest = found[0]
        return {
            "state": BINDING_RELOCATED,
            "code": RELOCATED_PROJECT,
            "root": str(repo),
            "configured_manifest": str(configured) if configured is not None else "",
            "configured_key": key,
            "configured_hooks": hooks,
            "manifest": str(manifest),
            "store": str(manifest.parent),
            "project_key": use_key,
            "history_recoverable": True,
        }
    if configured is not None or key or looks_like_ag2c_hooks_path(hooks):
        return {
            "state": BINDING_STALE,
            "code": STALE_EXTERNAL_STORE,
            "root": str(repo),
            "configured_manifest": str(configured) if configured is not None else "",
            "configured_key": key,
            "configured_hooks": hooks,
            "manifest": None,
            "store": None,
            "project_key": key or project_key(repo),
            "history_recoverable": False,
        }
    return _empty_binding(repo)


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
