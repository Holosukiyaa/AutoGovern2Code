from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .checks import run_checks
from .config import discover_manifest, load_manifest, load_policy
from .errors import AG2CError
from .gitops import change_digest, commit_change_digest, commit_changed_paths, git, head, repository_root, status_entries
from .index import build_index
from .slicer import compile_slice
from .util import digest_file, digest_json

RECEIPT_SCHEMA = "ag2c.receipt.v2"
LEGACY_RECEIPT_SCHEMA = "ag2c.receipt.v1"
LEGACY_RECEIPT_DIRECTORY = ".ag2c/receipts"
TASK_TRAILER = "AG2C-Task"
EVIDENCE_TRAILER = "AG2C-Evidence"
LEGACY_RECEIPT_TRAILER = "AG2C-Receipt"


def receipt_path(manifest, task_id: str) -> Path:
    return manifest.path.parent / "receipts" / f"{task_id}.json"


def build_receipt(manifest, policy, task: dict[str, Any]) -> dict[str, Any]:
    verification = task["verifications"][-1]
    receipt: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "project": manifest.project_id,
        "task_id": task["id"],
        "goal": task["goal"],
        "source_commit": task["source"]["head"],
        "source_branch": task["source"]["branch"],
        "entry": task["entry"],
        "changed_paths": verification["changed_paths"],
        "change_digest": verification["change_digest"],
        "route": {
            "state": verification["route_state"],
            "fallback_reasons": verification["route"]["fallback_reasons"],
            "fallback_targets": verification["route"]["fallback_targets"],
            "cards": verification["route_cards"],
            "slice_digest": verification["slice_digest"],
        },
        "checks": verification["checker_results"],
        "acceptance": verification["acceptance"],
        "verification_attempts": len(task["verifications"]),
        "failed_attempts": sum(not item.get("passed", False) for item in task["verifications"]),
        "correction_proven": any(
            item.get("kind") == "ai-correction-proven" for item in task.get("interventions", [])
        ),
        "blocked_actions": [
            item.get("kind")
            for item in task.get("interventions", [])
            if str(item.get("kind", "")).endswith("-blocked")
        ],
        "manifest_digest": digest_file(manifest.path),
        "policy_digest": digest_file(policy.path),
        "local_evidence": {
            "task_started": task.get("start_ledger_event_digest"),
            "check_run": verification.get("check_ledger_event_digest"),
            "verification": verification.get("ledger_event_digest"),
        },
        "verified_at": verification["occurred_at"],
    }
    receipt["receipt_digest"] = digest_json(receipt)
    return receipt


def write_receipt(manifest, receipt: dict[str, Any]) -> Path:
    path = receipt_path(manifest, str(receipt["task_id"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return path


def _load_receipt(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AG2CError(f"invalid AG2C evidence at {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") not in {RECEIPT_SCHEMA, LEGACY_RECEIPT_SCHEMA}:
        raise AG2CError(f"unsupported AG2C evidence at {path}")
    recorded = str(value.get("receipt_digest", ""))
    unsigned = dict(value)
    unsigned.pop("receipt_digest", None)
    if recorded != digest_json(unsigned):
        raise AG2CError(f"AG2C evidence digest mismatch at {path}")
    return value


def _commit_json(root: Path, commit: str, relative: str) -> dict[str, Any]:
    try:
        raw = git(root, "show", f"{commit}:{relative}", binary=True)
        assert isinstance(raw, bytes)
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, AssertionError, AG2CError) as exc:
        raise AG2CError(f"commit contains invalid AG2C evidence at {relative}") from exc
    if not isinstance(value, dict):
        raise AG2CError(f"commit contains invalid AG2C evidence at {relative}")
    return value


def _trailer(message: str, name: str) -> str:
    match = re.search(rf"(?m)^{re.escape(name)}:\s*(\S+)\s*$", message)
    return match.group(1) if match else ""


def _path_specs(manifest, paths: list[str]) -> list[str]:
    specs: list[str] = []
    for path in paths:
        matched = False
        for target in manifest.targets:
            prefix = target.path.replace("\\", "/").strip("./")
            relative = path
            if prefix:
                if path != prefix and not path.startswith(prefix + "/"):
                    continue
                relative = path[len(prefix):].strip("/")
            governed = any(
                root in {"", ".", "**"}
                or relative == root.replace("\\", "/").strip("/")
                or relative.startswith(root.replace("\\", "/").strip("/") + "/")
                for root in target.governed_roots
            )
            if governed:
                specs.append(f"{target.target_id}:{relative}")
                matched = True
                break
        if not matched:
            raise AG2CError(f"evidence contains an ungoverned path: {path}")
    return sorted(set(specs))


def verify_commit_receipt(start: Path, commit: str = "HEAD", *, rerun: bool = False) -> dict[str, Any]:
    root = repository_root(start)
    target = str(git(root, "rev-parse", commit)).strip()
    parents = str(git(root, "rev-list", "--parents", "-n", "1", target)).strip().split()
    if len(parents) != 2:
        raise AG2CError("AG2C evidence requires a single-parent governed commit")
    message = str(git(root, "show", "-s", "--format=%B", target))
    task_id = _trailer(message, TASK_TRAILER)
    recorded_digest = _trailer(message, EVIDENCE_TRAILER)
    legacy_relative = _trailer(message, LEGACY_RECEIPT_TRAILER)
    legacy = not task_id and bool(legacy_relative)
    if legacy:
        match = re.fullmatch(rf"{re.escape(LEGACY_RECEIPT_DIRECTORY)}/([a-z0-9][a-z0-9._-]*)\.json", legacy_relative)
        if not match:
            raise AG2CError("commit does not identify valid legacy AG2C evidence")
        task_id = match.group(1)
    elif not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", task_id):
        raise AG2CError("commit does not identify a valid AG2C task")
    manifest = load_manifest(discover_manifest(root), project_root=root)
    policy = load_policy(manifest)
    path = receipt_path(manifest, task_id)
    receipt = _load_receipt(path)
    if receipt.get("task_id") != task_id:
        raise AG2CError("external AG2C evidence task id does not match the commit")
    if legacy:
        if receipt.get("schema") != LEGACY_RECEIPT_SCHEMA:
            raise AG2CError("legacy AG2C commit does not match the external evidence format")
        committed_receipt = _commit_json(root, target, legacy_relative)
        if committed_receipt != receipt:
            raise AG2CError("legacy AG2C commit does not match the external evidence")
    elif receipt.get("schema") != RECEIPT_SCHEMA or receipt.get("receipt_digest") != recorded_digest:
        raise AG2CError("commit AG2C evidence digest does not match the external record")
    source = str(receipt.get("source_commit", ""))
    try:
        if not source:
            raise AG2CError("missing source")
        git(root, "merge-base", "--is-ancestor", source, target)
    except AG2CError as exc:
        raise AG2CError("AG2C evidence source is not an ancestor of the governed commit") from exc
    excluded = (LEGACY_RECEIPT_DIRECTORY,) if legacy else ()
    actual_paths = commit_changed_paths(root, source, target, exclude_prefixes=excluded)
    if receipt.get("changed_paths") != actual_paths:
        raise AG2CError("AG2C evidence changed paths do not match the commit")
    actual_digest = commit_change_digest(root, source, target, exclude_prefixes=excluded)
    if receipt.get("change_digest") != actual_digest:
        raise AG2CError("AG2C evidence content digest does not match the commit")
    if legacy:
        manifest_blob = str(git(root, "rev-parse", f"{target}:.ag2c/manifest.json")).strip()
        policy_blob = str(git(root, "rev-parse", f"{target}:.ag2c/policy.json")).strip()
        committed_manifest = _commit_json(root, target, ".ag2c/manifest.json")
        committed_project = committed_manifest.get("project", {}).get("id")
        if receipt.get("manifest_blob") != manifest_blob or receipt.get("policy_blob") != policy_blob:
            raise AG2CError("legacy AG2C configuration identity does not match the commit")
        if receipt.get("project") != committed_project:
            raise AG2CError("legacy AG2C evidence belongs to a different project")
    else:
        if receipt.get("project") != manifest.project_id:
            raise AG2CError("AG2C evidence belongs to a different project")
        if receipt.get("manifest_digest") != digest_file(manifest.path):
            raise AG2CError("current AG2C manifest does not match the evidence")
        if receipt.get("policy_digest") != digest_file(policy.path):
            raise AG2CError("current AG2C policy does not match the evidence")
    checks = receipt.get("checks")
    if not isinstance(checks, list) or not checks or any(
        not isinstance(item, dict) or item.get("status") != "passed" for item in checks
    ):
        raise AG2CError("AG2C evidence does not contain a passing checker result")
    rerun_report: dict[str, Any] | None = None
    if rerun:
        if legacy:
            raise AG2CError("externalized legacy AG2C evidence can be validated but not rerun")
        if target != head(root) or status_entries(root):
            raise AG2CError("evidence rerun requires a clean checkout at the governed commit")
        build_index(manifest, policy)
        entry = receipt.get("entry")
        route = receipt.get("route")
        if not isinstance(entry, dict) or not isinstance(route, dict):
            raise AG2CError("AG2C evidence entry or route is malformed")
        entry_slice = compile_slice(
            manifest,
            policy,
            path_specs=_path_specs(manifest, actual_paths),
            contract_specs=list(entry.get("contracts", [])),
            goal=str(receipt.get("goal", "")),
            all_mode=bool(entry.get("all", False)),
        )
        current_route = entry_slice["route"]
        current_cards = [item["id"] for item in entry_slice["cards"]]
        if (
            route.get("state") != current_route["state"]
            or route.get("fallback_reasons") != current_route["fallback_reasons"]
            or route.get("fallback_targets") != current_route["fallback_targets"]
            or route.get("cards") != current_cards
        ):
            raise AG2CError("current responsibility route does not match the AG2C evidence")
        if [item["id"] for item in entry_slice["check_plan"]] != [item.get("id") for item in checks]:
            raise AG2CError("current checker plan does not match the AG2C evidence")
        before_check_digest = change_digest(root, source)
        with tempfile.TemporaryDirectory(prefix="ag2c-ci-ledger-") as directory:
            rerun_report = run_checks(
                manifest,
                policy,
                entry_slice,
                ledger_path=Path(directory) / "ledger.jsonl",
                task_id=task_id,
            )
        after_check_digest = change_digest(root, source)
        if before_check_digest != after_check_digest:
            raise AG2CError("AG2C evidence rerun checker changed the governed bytes")
        if any(item["status"] != "passed" for item in rerun_report["results"]):
            raise AG2CError("AG2C evidence rerun failed")
        if rerun_report.get("acceptance") != receipt.get("acceptance"):
            raise AG2CError("AG2C evidence rerun acceptance does not match")
    return {
        "schema": "ag2c.local-evidence-verification.v1",
        "commit": target,
        "receipt_path": str(path),
        "receipt_digest": receipt["receipt_digest"],
        "local_evidence": "valid",
        "checks": len(checks),
        "rerun": "passed" if rerun_report is not None else "not-requested",
    }
