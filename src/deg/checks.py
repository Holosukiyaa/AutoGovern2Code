from __future__ import annotations

import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import DEGError
from .index import index_path, summary as index_summary, verify_freshness
from .ledger import append_event
from .model import Checker, Manifest, Policy
from .util import digest_file


def _clip(value: str, limit: int = 4000) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + f"\n... clipped {len(value) - limit} characters"


def _checker_cwd(manifest: Manifest, checker: Checker) -> Path:
    base = manifest.target_root(checker.target_id) if checker.target_id else manifest.project_root
    return (base / checker.cwd).resolve()


def run_checks(
    manifest: Manifest,
    policy: Policy,
    entry_slice: dict[str, Any],
    *,
    requested_checker_ids: set[str] | None = None,
    all_mode: bool = False,
    ledger_path: Path | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    current_errors = verify_freshness(manifest, policy, index_path(manifest))
    if current_errors:
        raise DEGError("index is not current:\n- " + "\n- ".join(current_errors))
    selected_ids = {str(item["id"]) for item in entry_slice["check_plan"]}
    if requested_checker_ids:
        unknown = sorted(requested_checker_ids - {checker.checker_id for checker in policy.checkers})
        if unknown:
            raise DEGError("unknown checker ids: " + ", ".join(unknown))
        not_selected = sorted(requested_checker_ids - selected_ids)
        if not_selected and not all_mode:
            raise DEGError("requested checkers are outside the entry slice: " + ", ".join(not_selected))
        selected_ids = requested_checker_ids
    if not selected_ids:
        raise DEGError("entry slice selected no checkers; add a real checker before reporting validation")
    results: list[dict[str, Any]] = []
    for checker in sorted(policy.checkers, key=lambda item: (item.stage, item.checker_id)):
        if checker.checker_id not in selected_ids:
            continue
        cwd = _checker_cwd(manifest, checker)
        started_at = datetime.now(timezone.utc).isoformat()
        started = time.monotonic()
        status = "error"
        exit_code: int | None = None
        stdout = ""
        stderr = ""
        if not cwd.is_dir():
            stderr = f"checker working directory does not exist: {cwd}"
        else:
            env = os.environ.copy()
            env.update(
                {
                    "DEG_PROJECT_ROOT": str(manifest.project_root),
                    "DEG_PROJECT_ID": manifest.project_id,
                    "DEG_SLICE_DIGEST": str(entry_slice["slice_digest"]),
                }
            )
            try:
                completed = subprocess.run(
                    list(checker.command),
                    cwd=cwd,
                    env=env,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=checker.timeout,
                    check=False,
                    shell=False,
                )
                exit_code = completed.returncode
                stdout = completed.stdout
                stderr = completed.stderr
                status = "passed" if completed.returncode == 0 else "failed"
            except subprocess.TimeoutExpired as exc:
                stdout = str(exc.stdout or "")
                stderr = f"checker timed out after {checker.timeout} seconds"
            except OSError as exc:
                stderr = f"cannot execute checker: {exc}"
        results.append(
            {
                "id": checker.checker_id,
                "stage": checker.stage,
                "target": checker.target_id,
                "status": status,
                "exit_code": exit_code,
                "started_at": started_at,
                "duration_ms": max(0, round((time.monotonic() - started) * 1000)),
                "command": list(checker.command),
                "cwd": str(cwd),
                "stdout": _clip(stdout),
                "stderr": _clip(stderr),
            }
        )
    acceptance: dict[str, str] = {}
    for stage in ("static", "floor", "boundary", "scenario"):
        policy_stage_ids = {checker.checker_id for checker in policy.checkers if checker.stage == stage}
        stage_results = [result for result in results if result["stage"] == stage]
        acceptance[stage] = (
            "not-applicable" if not policy_stage_ids
            else "not-run" if not stage_results
            else "passed" if all(result["status"] == "passed" for result in stage_results)
            else "failed" if any(result["status"] == "failed" for result in stage_results)
            else "error"
        )
    all_policy_ids = {checker.checker_id for checker in policy.checkers}
    complete = all_mode and selected_ids == all_policy_ids and all(result["status"] == "passed" for result in results)
    acceptance["complete"] = "passed" if complete else "not-run"
    report = {
        "schema": "deg.check-run.v1",
        "project": manifest.project_id,
        "slice_digest": entry_slice["slice_digest"],
        "route": entry_slice["route"],
        "manifest_digest": digest_file(manifest.path),
        "policy_digest": digest_file(policy.path),
        "index_facts_digest": index_summary(index_path(manifest))["facts_digest"],
        "results": results,
        "acceptance": acceptance,
    }
    if task_id is not None:
        report["task_id"] = task_id
    event = append_event(ledger_path or manifest.ledger_path, "check-run", report)
    report["ledger_sequence"] = event["sequence"]
    report["ledger_event_digest"] = event["event_digest"]
    return report
