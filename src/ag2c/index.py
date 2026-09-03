from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import AG2CError, IndexError as GovernanceIndexError
from .gitops import git_command_env, git_executable
from .model import Card, Manifest, Policy, Scope, Target
from .util import canonical_json, digest_file, digest_json, path_matches

INDEX_SCHEMA = "ag2c.index.v1"
INDEX_FILENAME = "index.sqlite"

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE target_revision (
    target_id TEXT PRIMARY KEY,
    repository_path TEXT NOT NULL,
    git_head TEXT NOT NULL,
    dirty_path_count INTEGER NOT NULL,
    artifact_count INTEGER NOT NULL,
    content_digest TEXT NOT NULL
);
CREATE TABLE artifact (
    artifact_id TEXT PRIMARY KEY,
    target_id TEXT NOT NULL REFERENCES target_revision(target_id),
    artifact_path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    content_digest TEXT NOT NULL,
    worktree_state TEXT NOT NULL,
    UNIQUE(target_id, artifact_path)
);
CREATE TABLE ownership (
    artifact_id TEXT PRIMARY KEY REFERENCES artifact(artifact_id),
    owner_card_ids_json TEXT NOT NULL,
    coverage_status TEXT NOT NULL
);
CREATE TABLE finding (
    finding_id TEXT PRIMARY KEY,
    severity TEXT NOT NULL,
    finding_type TEXT NOT NULL,
    artifact_id TEXT NOT NULL REFERENCES artifact(artifact_id),
    message TEXT NOT NULL
);
CREATE INDEX artifact_target_path_idx ON artifact(target_id, artifact_path);
CREATE INDEX finding_type_idx ON finding(finding_type, severity);
"""


def index_path(manifest: Manifest) -> Path:
    return manifest.state_dir / INDEX_FILENAME


def _git(root: Path, *args: str, binary: bool = False) -> str | bytes | None:
    try:
        executable = git_executable(root)
    except AG2CError:
        return None
    try:
        completed = subprocess.run(
            [executable, "-C", str(root), *args],
            check=False,
            capture_output=True,
            text=not binary,
            encoding=None if binary else "utf-8",
            env=git_command_env(executable=executable),
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def _under_root(path: str, root: str) -> bool:
    normalized = path.replace("\\", "/").strip("/")
    root = root.replace("\\", "/").strip("/")
    if root in {"", ".", "**"}:
        return True
    return normalized == root or normalized.startswith(root + "/")


def _excluded(path: str, patterns: tuple[str, ...]) -> bool:
    return any(path_matches(path, pattern) for pattern in patterns)


def _discover_files(root: Path, target: Target) -> tuple[list[str], dict[str, str], str, int]:
    if not root.is_dir():
        raise GovernanceIndexError(f"target directory does not exist: {target.target_id}:{root}")
    raw = _git(root, "ls-files", "-co", "--exclude-standard", "-z", "--", *target.governed_roots, binary=True)
    paths: set[str] = set()
    if isinstance(raw, bytes):
        paths = {
            item.decode("utf-8").replace("\\", "/")
            for item in raw.split(b"\0")
            if item
        }
    else:
        for governed_root in target.governed_roots:
            candidate = root / governed_root
            if candidate.is_file():
                paths.add(candidate.relative_to(root).as_posix())
            elif candidate.is_dir():
                paths.update(path.relative_to(root).as_posix() for path in candidate.rglob("*") if path.is_file())
    paths = {
        path for path in paths
        if any(_under_root(path, governed_root) for governed_root in target.governed_roots)
        and not _excluded(path, target.excludes)
        and (root / path).is_file()
    }
    status_raw = _git(root, "status", "--porcelain=v1", "-z", "--", *target.governed_roots, binary=True)
    states: dict[str, str] = {}
    if isinstance(status_raw, bytes):
        entries = [entry for entry in status_raw.split(b"\0") if entry]
        index = 0
        while index < len(entries):
            entry = entries[index]
            code = entry[:2].decode("ascii", errors="replace")
            relative = entry[3:].decode("utf-8", errors="replace").replace("\\", "/")
            states[relative] = "untracked" if code == "??" else "modified"
            if code[0] in {"R", "C"} and index + 1 < len(entries):
                index += 1
            index += 1
    head = _git(root, "rev-parse", "HEAD")
    git_head = str(head).strip() if isinstance(head, str) else "unversioned"
    return sorted(paths), states, git_head, len(states)


def _scope_matches(scope: Scope, target_id: str, artifact_path: str) -> bool:
    return (
        scope.target_id == target_id
        and any(path_matches(artifact_path, pattern) for pattern in scope.includes)
        and not any(path_matches(artifact_path, pattern) for pattern in scope.excludes)
    )


def primary_owners(policy: Policy, target_id: str, artifact_path: str) -> list[Card]:
    return sorted(
        (
            card for card in policy.cards
            if card.card_type == "floor"
            and any(
                scope.ownership == "primary" and _scope_matches(scope, target_id, artifact_path)
                for scope in card.scopes
            )
        ),
        key=lambda card: card.card_id,
    )


def _target_snapshot(manifest: Manifest, target: Target) -> dict[str, Any]:
    root = manifest.target_root(target.target_id)
    files, states, head, dirty_count = _discover_files(root, target)
    artifacts: list[dict[str, Any]] = []
    for relative in files:
        path = root / relative
        content = path.read_bytes()
        artifacts.append(
            {
                "artifact_id": f"{target.target_id}:{relative}",
                "target_id": target.target_id,
                "artifact_path": relative,
                "size_bytes": len(content),
                "content_digest": hashlib.sha256(content).hexdigest(),
                "worktree_state": states.get(relative, "tracked" if head != "unversioned" else "observed"),
            }
        )
    content_digest = hashlib.sha256(canonical_json(artifacts).encode("utf-8")).hexdigest()
    return {
        "target_id": target.target_id,
        "repository_path": str(root),
        "git_head": head,
        "dirty_path_count": dirty_count,
        "artifact_count": len(artifacts),
        "content_digest": content_digest,
        "artifacts": artifacts,
    }


def _index_facts_digest(connection: sqlite3.Connection) -> str:
    tables = {
        "targets": [
            list(row) for row in connection.execute(
                "SELECT target_id, repository_path, git_head, dirty_path_count, artifact_count, content_digest "
                "FROM target_revision ORDER BY target_id"
            )
        ],
        "artifacts": [
            list(row) for row in connection.execute(
                "SELECT artifact_id, target_id, artifact_path, size_bytes, content_digest, worktree_state "
                "FROM artifact ORDER BY artifact_id"
            )
        ],
        "ownership": [list(row) for row in connection.execute("SELECT * FROM ownership ORDER BY artifact_id")],
        "findings": [list(row) for row in connection.execute("SELECT * FROM finding ORDER BY finding_id")],
    }
    return digest_json(tables)


def build_index(manifest: Manifest, policy: Policy, destination: Path | None = None) -> Path:
    destination = (destination or index_path(manifest)).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    snapshots = [_target_snapshot(manifest, target) for target in manifest.targets]
    handle, temporary_name = tempfile.mkstemp(prefix="ag2c-index-", suffix=".sqlite", dir=destination.parent)
    os.close(handle)
    temporary = Path(temporary_name)
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(temporary)
        connection.executescript(SCHEMA_SQL)
        metadata = {
            "schema": INDEX_SCHEMA,
            "schema_version": "1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "manifest_digest": digest_file(manifest.path),
            "policy_digest": digest_file(policy.path),
            "project_id": manifest.project_id,
        }
        connection.executemany("INSERT INTO metadata VALUES (?, ?)", sorted(metadata.items()))
        for snapshot in snapshots:
            connection.execute(
                "INSERT INTO target_revision VALUES (?, ?, ?, ?, ?, ?)",
                (
                    snapshot["target_id"], snapshot["repository_path"], snapshot["git_head"],
                    snapshot["dirty_path_count"], snapshot["artifact_count"], snapshot["content_digest"],
                ),
            )
            for artifact in snapshot["artifacts"]:
                connection.execute(
                    "INSERT INTO artifact VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        artifact["artifact_id"], artifact["target_id"], artifact["artifact_path"],
                        artifact["size_bytes"], artifact["content_digest"], artifact["worktree_state"],
                    ),
                )
                owners = primary_owners(policy, artifact["target_id"], artifact["artifact_path"])
                status = "covered" if len(owners) == 1 else "uncovered" if not owners else "ambiguous"
                owner_ids = [owner.card_id for owner in owners]
                connection.execute(
                    "INSERT INTO ownership VALUES (?, ?, ?)",
                    (artifact["artifact_id"], canonical_json(owner_ids), status),
                )
                if status != "covered":
                    finding_id = hashlib.sha256(f"{status}:{artifact['artifact_id']}".encode("utf-8")).hexdigest()
                    message = (
                        f"No primary floor owns {artifact['artifact_id']}"
                        if status == "uncovered"
                        else f"Multiple primary floors own {artifact['artifact_id']}: {', '.join(owner_ids)}"
                    )
                    connection.execute(
                        "INSERT INTO finding VALUES (?, 'error', ?, ?, ?)",
                        (finding_id, f"scope-{status}", artifact["artifact_id"], message),
                    )
        facts_digest = _index_facts_digest(connection)
        connection.execute("INSERT INTO metadata VALUES ('facts_digest', ?)", (facts_digest,))
        connection.commit()
        errors = verify_index(temporary)
        if errors:
            raise GovernanceIndexError("generated index is invalid:\n- " + "\n- ".join(errors))
        connection.close()
        connection = None
        os.replace(temporary, destination)
        return destination
    finally:
        if connection is not None:
            connection.close()
        temporary.unlink(missing_ok=True)


def verify_index(path: Path) -> list[str]:
    if not path.is_file():
        return [f"index does not exist: {path}"]
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    errors: list[str] = []
    try:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            errors.append("SQLite integrity check failed")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            errors.append("SQLite foreign key check failed")
        metadata = dict(connection.execute("SELECT key, value FROM metadata"))
        if metadata.get("schema") != INDEX_SCHEMA:
            errors.append(f"index schema must be {INDEX_SCHEMA}")
        elif metadata.get("facts_digest") != _index_facts_digest(connection):
            errors.append("index facts digest mismatch")
        artifact_count = connection.execute("SELECT COUNT(*) FROM artifact").fetchone()[0]
        ownership_count = connection.execute("SELECT COUNT(*) FROM ownership").fetchone()[0]
        target_count = connection.execute("SELECT COUNT(*) FROM target_revision").fetchone()[0]
        declared_count = connection.execute("SELECT COALESCE(SUM(artifact_count), 0) FROM target_revision").fetchone()[0]
        if artifact_count != ownership_count or artifact_count != declared_count:
            errors.append("artifact, ownership, and target counts are inconsistent")
        if target_count < 1:
            errors.append("index must contain at least one target")
    except sqlite3.Error as exc:
        errors.append(f"cannot inspect index: {exc}")
    finally:
        connection.close()
    return errors


def verify_freshness(manifest: Manifest, policy: Policy, path: Path | None = None) -> list[str]:
    path = (path or index_path(manifest)).resolve()
    errors = verify_index(path)
    if errors:
        return errors
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    try:
        metadata = dict(connection.execute("SELECT key, value FROM metadata"))
        revisions = {
            row[0]: row[1:]
            for row in connection.execute(
                "SELECT target_id, repository_path, git_head, dirty_path_count, artifact_count, content_digest "
                "FROM target_revision"
            )
        }
    finally:
        connection.close()
    if metadata.get("manifest_digest") != digest_file(manifest.path):
        errors.append("index is stale: manifest changed")
    if metadata.get("policy_digest") != digest_file(policy.path):
        errors.append("index is stale: policy changed")
    for target in manifest.targets:
        snapshot = _target_snapshot(manifest, target)
        recorded = revisions.get(target.target_id)
        current = (
            snapshot["repository_path"], snapshot["git_head"], snapshot["dirty_path_count"],
            snapshot["artifact_count"], snapshot["content_digest"],
        )
        if recorded is None:
            errors.append(f"index is stale: target missing: {target.target_id}")
        elif tuple(recorded) != current:
            labels = ("repository path", "Git HEAD", "dirty path count", "artifact count", "governed content")
            for label, old, new in zip(labels, recorded, current):
                if old != new:
                    errors.append(f"index is stale: {target.target_id} {label} changed")
    return errors


def summary(path: Path) -> dict[str, Any]:
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        metadata = dict(connection.execute("SELECT key, value FROM metadata"))
        targets = [
            dict(zip(("target_id", "git_head", "dirty_path_count", "artifact_count", "content_digest"), row))
            for row in connection.execute(
                "SELECT target_id, git_head, dirty_path_count, artifact_count, content_digest "
                "FROM target_revision ORDER BY target_id"
            )
        ]
        coverage = dict(connection.execute("SELECT coverage_status, COUNT(*) FROM ownership GROUP BY coverage_status"))
        return {"schema": metadata.get("schema"), "facts_digest": metadata.get("facts_digest"), "targets": targets, "coverage": coverage}
    finally:
        connection.close()


def findings(path: Path) -> list[dict[str, str]]:
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return [
            dict(zip(("finding_id", "severity", "finding_type", "artifact_id", "message"), row))
            for row in connection.execute(
                "SELECT finding_id, severity, finding_type, artifact_id, message FROM finding ORDER BY severity, artifact_id"
            )
        ]
    finally:
        connection.close()
