from __future__ import annotations

import json
import os
import secrets
import shutil
from pathlib import Path
from typing import Any, Iterable

from .errors import AG2CError
from .gitops import git, head

TRANSACTION_SCHEMA = "ag2c.lifecycle-transaction.v1"


def _storage(root: Path) -> Path:
    common = Path(str(git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")).strip())
    return common / "ag2c-lifecycle"


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _copy_path(source: Path, destination: Path) -> str:
    if source.is_symlink():
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.symlink_to(os.readlink(source), target_is_directory=source.is_dir())
        return "symlink"
    if source.is_dir():
        shutil.copytree(source, destination, symlinks=True)
        return "directory"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return "file"


def _restore(root: Path, journal: dict[str, Any]) -> None:
    backup_root = Path(str(journal["backup_root"]))
    for item in journal["paths"]:
        target = root / str(item["path"])
        if target.exists() or target.is_symlink():
            _remove_path(target)
        if item["existed"]:
            _copy_path(backup_root / str(item["backup"]), target)
    previous_hooks = str(journal.get("previous_hooks_path", ""))
    if previous_hooks:
        git(root, "config", "core.hooksPath", previous_hooks)
    else:
        git(root, "config", "--unset-all", "core.hooksPath", check=False)
    tracked_paths = [str(item["path"]) for item in journal["paths"]]
    if tracked_paths:
        git(root, "restore", "--staged", "--source", str(journal["starting_head"]), "--", *tracked_paths, check=False)


def _clear(storage: Path, journal: dict[str, Any] | None = None) -> None:
    pointer = storage / "current.json"
    if pointer.exists():
        pointer.unlink()
    if journal:
        backup = Path(str(journal.get("backup_root", "")))
        if backup.is_dir() and backup.parent == storage / "backups":
            shutil.rmtree(backup)


def recover_lifecycle(root: Path) -> dict[str, str]:
    storage = _storage(root)
    pointer = storage / "current.json"
    if not pointer.is_file():
        return {"action": "none"}
    try:
        journal = json.loads(pointer.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AG2CError(f"cannot recover interrupted AG2C lifecycle transaction: {exc}") from exc
    if not isinstance(journal, dict) or journal.get("schema") != TRANSACTION_SCHEMA:
        raise AG2CError("cannot recover an unsupported AG2C lifecycle transaction")
    if Path(str(journal.get("root", ""))).resolve() != root.resolve():
        raise AG2CError("AG2C lifecycle transaction belongs to a different worktree")
    if head(root) != journal.get("starting_head"):
        _clear(storage, journal)
        return {"action": "kept-committed", "operation": str(journal.get("operation", "unknown"))}
    _restore(root, journal)
    _clear(storage, journal)
    return {"action": "rolled-back", "operation": str(journal.get("operation", "unknown"))}


def lifecycle_pending(root: Path) -> bool:
    return (_storage(root) / "current.json").is_file()


class LifecycleTransaction:
    def __init__(self, root: Path, operation: str, paths: Iterable[str]):
        self.root = root.resolve()
        self.operation = operation
        self.paths = list(dict.fromkeys(path.replace("\\", "/") for path in paths))
        self.storage = _storage(self.root)
        self.journal: dict[str, Any] | None = None

    def __enter__(self) -> "LifecycleTransaction":
        recover_lifecycle(self.root)
        self.storage.mkdir(parents=True, exist_ok=True)
        backup_root = self.storage / "backups" / secrets.token_hex(8)
        backup_root.mkdir(parents=True)
        snapshots: list[dict[str, Any]] = []
        for index, relative in enumerate(self.paths):
            source = self.root / relative
            existed = source.exists() or source.is_symlink()
            snapshot: dict[str, Any] = {
                "path": relative,
                "existed": existed,
                "backup": str(index),
                "kind": "missing",
            }
            if existed:
                snapshot["kind"] = _copy_path(source, backup_root / str(index))
            snapshots.append(snapshot)
        self.journal = {
            "schema": TRANSACTION_SCHEMA,
            "operation": self.operation,
            "root": str(self.root),
            "starting_head": head(self.root),
            "previous_hooks_path": str(git(self.root, "config", "--get", "core.hooksPath", check=False)).strip(),
            "backup_root": str(backup_root),
            "paths": snapshots,
        }
        _atomic_json(self.storage / "current.json", self.journal)
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        assert self.journal is not None
        if exc_type is not None and head(self.root) == self.journal["starting_head"]:
            _restore(self.root, self.journal)
        _clear(self.storage, self.journal)
        return False
