"""5.1 可信基变更仪式：改 GOVERNANCE_CODE_PATHS 必须申报说明书，finish 必须人批。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import AG2CError
from .util import atomic_json_write, digest_file

TRUST_ANCHOR_SCHEMA = "ag2c.trust-anchor.v1"
_STATEMENT_KEYS = ("why", "risk", "rollback", "verify")


def trust_base_hits(changed_paths: list[str]) -> list[str]:
    from .tasks import GOVERNANCE_CODE_PATHS

    wanted = set(GOVERNANCE_CODE_PATHS)
    hits: list[str] = []
    for raw in changed_paths:
        rel = str(raw).replace("\\", "/").split(":", 1)[-1].lstrip("./")
        if rel in wanted:
            hits.append(rel)
    return hits


def _statement_ok(blob: dict[str, Any]) -> bool:
    return all(str(blob.get(key) or "").strip() for key in _STATEMENT_KEYS)


def require_trust_base_declaration(task: dict[str, Any], changed_paths: list[str]) -> None:
    if not trust_base_hits(changed_paths):
        return
    decl = (task.get("entry") or {}).get("trust_base")
    stmt = decl.get("statement") if isinstance(decl, dict) else None
    if not (isinstance(decl, dict) and decl.get("declared") and isinstance(stmt, dict) and _statement_ok(stmt)):
        raise AG2CError(
            "trust-base ceremony: declare with `ag2c task declare --trust-base --why --risk --rollback --verify-how` before verify"
        )


def require_trust_base_approval(task: dict[str, Any], changed_paths: list[str]) -> None:
    if not trust_base_hits(changed_paths):
        return
    if not any(item.get("kind") == "trust-base-approved" for item in task.get("interventions") or []):
        raise AG2CError("trust-base ceremony: `ag2c task approve --trust-base --actor --reason` before finish")


def declare_trust_base(
    start: Path,
    *,
    reason: str,
    why: str,
    risk: str,
    rollback: str,
    verify: str,
) -> dict[str, Any]:
    from .tasks import _canonical_manifest, _now, _record_intervention, _require_open_task, _task_from_worktree

    reason, why, risk, rollback, verify = (value.strip() for value in (reason, why, risk, rollback, verify))
    if not reason or not _statement_ok({"why": why, "risk": risk, "rollback": rollback, "verify": verify}):
        raise AG2CError("trust-base declaration requires --reason --why --risk --rollback --verify-how")
    canonical, task = _task_from_worktree(start)
    _require_open_task(task)
    statement = {"why": why, "risk": risk, "rollback": rollback, "verify": verify}
    declaration = {"declared": True, "reason": reason, "at": _now(), "via": "declare", "statement": statement}
    task.setdefault("entry", {})["trust_base"] = declaration
    _record_intervention(
        canonical,
        _canonical_manifest(canonical)[0],
        task,
        "trust-base-declared",
        {"reason": reason, "via": "declare", "statement": statement},
    )
    return {"task": task["id"], "trust_base": declaration}


def approve_trust_base(start: Path, *, actor: str, reason: str) -> dict[str, Any]:
    from .tasks import _canonical_manifest, _record_intervention, _require_open_task, _task_from_worktree

    actor, reason = actor.strip(), reason.strip()
    if not actor or not reason:
        raise AG2CError("trust-base approval requires --actor and --reason")
    canonical, task = _task_from_worktree(start)
    _require_open_task(task)
    _record_intervention(
        canonical,
        _canonical_manifest(canonical)[0],
        task,
        "trust-base-approved",
        {"actor": actor, "reason": reason},
    )
    return {"task": task["id"], "approved": True, "actor": actor}


def write_trust_anchor(start: Path, *, actor: str, reason: str) -> dict[str, Any]:
    from .config import discover_manifest, load_manifest
    from .gitops import repository_root
    from .ledger import append_event, ledger_summary

    actor, reason = actor.strip(), reason.strip()
    if not actor or not reason:
        raise AG2CError("trust-anchor requires --actor and --reason")
    root = repository_root(start)
    manifest = load_manifest(discover_manifest(root), project_root=root)
    snapshot = {
        "schema": TRUST_ANCHOR_SCHEMA,
        "ledger_digest": str(ledger_summary(manifest.ledger_path)["head_digest"]),
        "policy_digest": digest_file(manifest.policy_path),
        "actor": actor,
        "reason": reason,
        "signature": "",
    }
    event = append_event(
        manifest.ledger_path,
        "trust-anchor",
        {"actor": actor, "reason": reason, "ledger_digest": snapshot["ledger_digest"], "policy_digest": snapshot["policy_digest"]},
    )
    snapshot["ledger_event_digest"] = event["event_digest"]
    atomic_json_write(manifest.state_dir / "trust-anchor.json", snapshot)
    return snapshot
