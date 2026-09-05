from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import AG2CError
from .gitops import git_command_env, git_executable, peek_git_executable
from .index import index_path, summary as index_summary, verify_freshness
from .ledger import append_event
from .model import Checker, Manifest, Policy
from .util import digest_file

SKIP_EXIT_CODE = 78
SKIP_MARK = "AG2C_SKIP:"
PROCESS_CHECK_STATUSES = frozenset({"passed", "skipped"})


def _clip(value: str, limit: int = 4000) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + f"\n... clipped {len(value) - limit} characters"


def _checker_cwd(manifest: Manifest, checker: Checker) -> Path:
    base = manifest.target_root(checker.target_id) if checker.target_id else manifest.project_root
    return (base / checker.cwd).resolve()


def environment_snapshot() -> dict[str, Any]:
    git_path = peek_git_executable()
    return {
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "has_git": git_path is not None,
        "git": git_path,
        "has_node": shutil.which("node") is not None,
        "has_go": shutil.which("go") is not None,
        "data_roots": {
            key: os.environ[key]
            for key in sorted(os.environ)
            if key.endswith("_DATA_ROOT")
        },
    }


def _skip_reason(exit_code: int | None, stdout: str, stderr: str) -> str | None:
    for line in f"{stdout}\n{stderr}".splitlines():
        stripped = line.strip()
        if stripped.startswith(SKIP_MARK):
            return stripped[len(SKIP_MARK):].strip() or "skipped"
    if exit_code == SKIP_EXIT_CODE:
        return "checker reported skip"
    return None


def _stage_acceptance(stage_results: list[dict[str, Any]]) -> str:
    statuses = {str(item.get("status")) for item in stage_results}
    if "failed" in statuses:
        return "failed"
    if "error" in statuses:
        return "error"
    if "skipped" in statuses:
        return "skipped"
    return "passed"


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
        raise AG2CError("index is not current:\n- " + "\n- ".join(current_errors))
    selected_ids = {str(item["id"]) for item in entry_slice["check_plan"]}
    if requested_checker_ids:
        unknown = sorted(requested_checker_ids - {checker.checker_id for checker in policy.checkers})
        if unknown:
            raise AG2CError("unknown checker ids: " + ", ".join(unknown))
        not_selected = sorted(requested_checker_ids - selected_ids)
        if not_selected and not all_mode:
            raise AG2CError("requested checkers are outside the entry slice: " + ", ".join(not_selected))
        selected_ids = requested_checker_ids
    if not selected_ids:
        raise AG2CError("entry slice selected no checkers; add a real checker before reporting validation")
    from .households import enforce_households

    enforce_households(manifest, policy, entry_slice, selected_ids)
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
            env = git_command_env(executable=git_executable(manifest.project_root))
            env.update(
                {
                    "AG2C_PROJECT_ROOT": str(manifest.project_root),
                    "AG2C_PROJECT_ID": manifest.project_id,
                    "AG2C_SLICE_DIGEST": str(entry_slice["slice_digest"]),
                    "AG2C_IMPLEMENTATION": checker.implementation,
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
                skipped = _skip_reason(exit_code, stdout, stderr)
                if skipped:
                    if policy.household_required and checker.implementation:
                        status = "failed"
                        stderr += "\nRequired implementation check was skipped: " + skipped
                    else:
                        status = "skipped"
                elif completed.returncode == 0:
                    status = "passed"
                else:
                    status = "failed"
            except subprocess.TimeoutExpired as exc:
                stdout = str(exc.stdout or "")
                stderr = f"checker timed out after {checker.timeout} seconds"
            except OSError as exc:
                stderr = f"cannot execute checker: {exc}"
        result = {
            "id": checker.checker_id,
            "stage": checker.stage,
            "target": checker.target_id,
            "status": status,
            "exit_code": exit_code,
            "started_at": started_at,
            "duration_ms": max(0, round((time.monotonic() - started) * 1000)),
            "command": list(checker.command),
            "implementation": checker.implementation,
            "cwd": str(cwd),
            "stdout": _clip(stdout),
            "stderr": _clip(stderr),
        }
        if status == "skipped":
            result["skip_reason"] = _skip_reason(exit_code, stdout, stderr) or "skipped"
        results.append(result)
    acceptance: dict[str, str] = {}
    for stage in ("static", "floor", "boundary", "scenario"):
        policy_stage_ids = {checker.checker_id for checker in policy.checkers if checker.stage == stage}
        stage_results = [result for result in results if result["stage"] == stage]
        acceptance[stage] = (
            "not-applicable" if not policy_stage_ids
            else "not-run" if not stage_results
            else _stage_acceptance(stage_results)
        )
    all_policy_ids = {checker.checker_id for checker in policy.checkers}
    complete = all_mode and selected_ids == all_policy_ids and all(result["status"] == "passed" for result in results)
    acceptance["complete"] = "passed" if complete else "not-run"
    report = {
        "schema": "ag2c.check-run.v1",
        "project": manifest.project_id,
        "slice_digest": entry_slice["slice_digest"],
        "route": entry_slice["route"],
        "manifest_digest": digest_file(manifest.path),
        "policy_digest": digest_file(policy.path),
        "index_facts_digest": index_summary(index_path(manifest))["facts_digest"],
        "results": results,
        "acceptance": acceptance,
        "environment": environment_snapshot(),
    }
    if task_id is not None:
        report["task_id"] = task_id
    event = append_event(ledger_path or manifest.ledger_path, "check-run", report)
    report["ledger_sequence"] = event["sequence"]
    report["ledger_event_digest"] = event["event_digest"]
    return report
