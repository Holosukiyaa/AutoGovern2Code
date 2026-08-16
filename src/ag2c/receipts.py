from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .checks import run_checks
from .config import load_manifest, load_policy
from .errors import AG2CError
from .gitops import change_digest, commit_change_digest, commit_changed_paths, git, head, repository_root, status_entries
from .index import build_index
from .slicer import compile_slice
from .util import digest_json

RECEIPT_SCHEMA = "ag2c.receipt.v1"
RECEIPT_DIRECTORY = ".ag2c/receipts"


def receipt_relative_path(task_id: str) -> str:
    return f"{RECEIPT_DIRECTORY}/{task_id}.json"


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
        "manifest_blob": str(git(manifest.project_root, "rev-parse", "HEAD:.ag2c/manifest.json")).strip(),
        "policy_blob": str(git(manifest.project_root, "rev-parse", "HEAD:.ag2c/policy.json")).strip(),
        "local_evidence": {
            "task_started": task.get("start_ledger_event_digest"),
            "check_run": verification.get("check_ledger_event_digest"),
            "verification": verification.get("ledger_event_digest"),
        },
        "verified_at": verification["occurred_at"],
    }
    receipt["receipt_digest"] = digest_json(receipt)
    return receipt


def write_receipt(root: Path, receipt: dict[str, Any]) -> Path:
    path = root / receipt_relative_path(str(receipt["task_id"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return path


def _commit_file(root: Path, commit: str, path: str) -> bytes:
    value = git(root, "show", f"{commit}:{path}", binary=True)
    assert isinstance(value, bytes)
    return value


def _load_commit_receipt(root: Path, commit: str, path: str) -> dict[str, Any]:
    try:
        value = json.loads(_commit_file(root, commit, path).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AG2CError(f"invalid AG2C receipt at {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") != RECEIPT_SCHEMA:
        raise AG2CError(f"unsupported AG2C receipt at {path}")
    recorded = str(value.get("receipt_digest", ""))
    unsigned = dict(value)
    unsigned.pop("receipt_digest", None)
    if recorded != digest_json(unsigned):
        raise AG2CError(f"AG2C receipt digest mismatch at {path}")
    return value


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
            raise AG2CError(f"receipt contains an ungoverned path: {path}")
    return sorted(set(specs))


def verify_commit_receipt(start: Path, commit: str = "HEAD", *, rerun: bool = False) -> dict[str, Any]:
    root = repository_root(start)
    target = str(git(root, "rev-parse", commit)).strip()
    parent_line = str(git(root, "rev-list", "--parents", "-n", "1", target)).strip().split()
    if len(parent_line) != 2:
        raise AG2CError("AG2C receipts require a single-parent governed commit")
    immediate_parent = parent_line[1]
    receipt_paths = [
        path
        for path in commit_changed_paths(root, immediate_parent, target)
        if path.startswith(RECEIPT_DIRECTORY + "/") and path.endswith(".json")
    ]
    if len(receipt_paths) != 1:
        raise AG2CError("governed commit must add or update exactly one AG2C receipt")
    receipt_path = receipt_paths[0]
    receipt = _load_commit_receipt(root, target, receipt_path)
    task_id = receipt.get("task_id")
    if (
        not isinstance(task_id, str)
        or not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", task_id)
        or receipt_path != receipt_relative_path(task_id)
    ):
        raise AG2CError("AG2C receipt path does not match its task id")
    source = str(receipt.get("source_commit", ""))
    try:
        if not source:
            raise AG2CError("missing source")
        git(root, "merge-base", "--is-ancestor", source, target)
    except AG2CError as exc:
        raise AG2CError("AG2C receipt source is not an ancestor of the governed commit") from exc
    actual_paths = commit_changed_paths(root, source, target, exclude_prefixes=(RECEIPT_DIRECTORY,))
    if receipt.get("changed_paths") != actual_paths:
        raise AG2CError("AG2C receipt changed paths do not match the commit")
    actual_digest = commit_change_digest(root, source, target, exclude_prefixes=(RECEIPT_DIRECTORY,))
    if receipt.get("change_digest") != actual_digest:
        raise AG2CError("AG2C receipt content digest does not match the commit")
    manifest_blob = str(git(root, "rev-parse", f"{target}:.ag2c/manifest.json")).strip()
    policy_blob = str(git(root, "rev-parse", f"{target}:.ag2c/policy.json")).strip()
    if receipt.get("manifest_blob") != manifest_blob:
        raise AG2CError("AG2C receipt manifest identity does not match the commit")
    if receipt.get("policy_blob") != policy_blob:
        raise AG2CError("AG2C receipt policy identity does not match the commit")
    try:
        committed_manifest = json.loads(_commit_file(root, target, ".ag2c/manifest.json").decode("utf-8"))
        committed_project = committed_manifest["project"]["id"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise AG2CError("governed commit contains an invalid AG2C Manifest") from exc
    if receipt.get("project") != committed_project:
        raise AG2CError("AG2C receipt project does not match the committed Manifest")
    checks = receipt.get("checks")
    if not isinstance(checks, list) or not checks or any(
        not isinstance(item, dict) or item.get("status") != "passed" for item in checks
    ):
        raise AG2CError("AG2C receipt does not contain a passing checker result")
    rerun_report: dict[str, Any] | None = None
    if rerun:
        if target != head(root) or status_entries(root):
            raise AG2CError("CI rerun requires a clean checkout at the receipt commit")
        manifest = load_manifest(root / ".ag2c" / "manifest.json")
        policy = load_policy(manifest)
        build_index(manifest, policy)
        path_specs = _path_specs(manifest, actual_paths)
        entry = receipt.get("entry")
        route = receipt.get("route")
        if not isinstance(entry, dict) or not isinstance(route, dict):
            raise AG2CError("AG2C receipt entry or route is malformed")
        entry_slice = compile_slice(
            manifest,
            policy,
            path_specs=path_specs,
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
            raise AG2CError("current responsibility route does not match the AG2C receipt")
        selected = [item["id"] for item in entry_slice["check_plan"]]
        recorded = [item.get("id") for item in checks]
        if selected != recorded:
            raise AG2CError("current trusted checker plan does not match the AG2C receipt")
        before_check_digest = change_digest(root, source, exclude_prefixes=(RECEIPT_DIRECTORY,))
        with tempfile.TemporaryDirectory(prefix="ag2c-ci-ledger-") as directory:
            rerun_report = run_checks(
                manifest,
                policy,
                entry_slice,
                ledger_path=Path(directory) / "ledger.jsonl",
                task_id=str(receipt["task_id"]),
            )
        after_check_digest = change_digest(root, source, exclude_prefixes=(RECEIPT_DIRECTORY,))
        if before_check_digest != after_check_digest:
            raise AG2CError("AG2C CI rerun checker changed the governed bytes")
        if any(item["status"] != "passed" for item in rerun_report["results"]):
            raise AG2CError("AG2C CI rerun failed")
        if rerun_report.get("acceptance") != receipt.get("acceptance"):
            raise AG2CError("AG2C CI acceptance does not match the receipt")
    return {
        "schema": "ag2c.ci-verification.v1",
        "commit": target,
        "receipt_path": receipt_path,
        "receipt_digest": receipt["receipt_digest"],
        "portable_receipt": "valid",
        "checks": len(checks),
        "rerun": "passed" if rerun_report is not None else "not-requested",
    }
