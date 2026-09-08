from __future__ import annotations

import ast
import json
import os
import re
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
from .util import digest_file, hidden_process_kwargs

SKIP_EXIT_CODE = 78
SKIP_MARK = "AG2C_SKIP:"
PROCESS_CHECK_STATUSES = frozenset({"passed", "skipped"})

TEST_BASELINE_SCHEMA = "ag2c.test-baseline.v1"
TEST_BASELINE_FILENAME = "test-baseline.json"
_UNITTEST_FAILURE_RE = re.compile(r"^(?:FAIL|ERROR):\s+(\S+(?:\s+\([^)]*\))?)\s*$", re.MULTILINE)
DEFAULT_BASELINE_SUNSET_DAYS = 30


def test_baseline_path(manifest: Manifest) -> Path:
    return manifest.state_dir / TEST_BASELINE_FILENAME


def load_test_baseline(manifest: Manifest) -> dict[str, list[str]]:
    path = test_baseline_path(manifest)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    checkers = raw.get("checkers") if isinstance(raw, dict) else None
    if not isinstance(checkers, dict):
        return {}
    baseline: dict[str, list[str]] = {}
    now = datetime.now(timezone.utc)
    for checker_id, record in checkers.items():
        failures = record.get("failures") if isinstance(record, dict) else None
        if isinstance(failures, list):
            # Sunset: expired baseline entries are treated as new failures.
            expires = str(record.get("expires_at") or "")
            if expires:
                try:
                    if datetime.fromisoformat(expires) < now:
                        continue  # expired — do not exempt
                except ValueError:
                    pass
            baseline[str(checker_id)] = sorted({str(item) for item in failures})
    return baseline


def _save_test_baseline(manifest: Manifest, baseline: dict[str, list[str]], *, actor: str, reason: str, sunset_days: int = DEFAULT_BASELINE_SUNSET_DAYS) -> None:
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    expires = (now + timedelta(days=sunset_days)).isoformat()
    records = {
        checker_id: {
            "failures": sorted(failures),
            "updated_at": now.isoformat(),
            "expires_at": expires,
            "actor": actor,
            "reason": reason,
        }
        for checker_id, failures in sorted(baseline.items())
        if failures
    }
    payload = {"schema": TEST_BASELINE_SCHEMA, "checkers": records}
    path = test_baseline_path(manifest)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    append_event(
        manifest.ledger_path,
        "test-baseline",
        {
            "schema": TEST_BASELINE_SCHEMA,
            "project": manifest.project_id,
            "checkers": {checker_id: len(record["failures"]) for checker_id, record in records.items()},
            "actor": actor,
            "reason": reason,
        },
    )


def parse_unittest_failures(output: str) -> list[str]:
    """Extract failing test ids from unittest output (FAIL:/ERROR: lines)."""
    return sorted(set(_UNITTEST_FAILURE_RE.findall(output)))


DOCS_ONLY_SUFFIXES = frozenset({".md", ".markdown", ".rst", ".txt", ".adoc"})


def _budget_warnings(manifest: Manifest, policy: Policy, entry_slice: dict[str, Any]) -> list[dict[str, str]]:
    """Soft budget: warn when a room's code exceeds its budget_lines. Never blocks."""
    warnings: list[dict[str, str]] = []
    from .households import census_report
    try:
        report = census_report(manifest, policy)
    except Exception:
        return warnings
    for item in report.get("households") or []:
        if not isinstance(item, dict):
            continue
        card = policy.card(str(item.get("id") or ""))
        if card is None or card.budget_lines <= 0:
            continue
        code_count = int(item.get("code_count") or 0)
        if code_count > card.budget_lines:
            warnings.append({
                "kind": "over-budget",
                "room": str(item.get("id") or ""),
                "detail": f"{code_count} 行代码，预算 {card.budget_lines} 行（超出 {code_count - card.budget_lines} 行）",
            })
    return warnings


def _duplicate_warnings(manifest: Manifest, entry_slice: dict[str, Any]) -> list[dict[str, str]]:
    """Soft duplicate detection: warn when new functions look like existing ones.

    Uses AST to extract function names + body line counts. A new function is
    flagged when an existing function has the same name or a body within 20%
    line count and the same argument count.
    """
    warnings: list[dict[str, str]] = []
    entries = entry_slice.get("entries") if isinstance(entry_slice, dict) else None
    artifacts = entries.get("paths") if isinstance(entries, dict) else None
    if not artifacts:
        return warnings
    changed_py = [
        str(item.get("path") or "")
        for item in artifacts
        if isinstance(item, dict) and str(item.get("path") or "").endswith(".py")
    ]
    if not changed_py:
        return warnings
    # Collect all functions from changed files.
    new_funcs: list[tuple[str, str, int, int]] = []  # (file, name, args, body_lines)
    for rel in changed_py:
        path = manifest.project_root / rel
        if not path.is_file():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                body_lines = (node.end_lineno or 0) - (node.lineno or 0)
                new_funcs.append((rel, node.name, len(node.args.args), body_lines))
    if not new_funcs:
        return warnings
    # Collect existing functions from all governed Python files.
    from .index import _discover_files
    existing: list[tuple[str, str, int, int]] = []
    for target in manifest.targets:
        root = manifest.target_root(target.target_id)
        paths, _, _, _ = _discover_files(root, target)
        for rel in paths:
            if not rel.endswith(".py") or rel in changed_py:
                continue
            path = root / rel
            if not path.is_file():
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    body_lines = (node.end_lineno or 0) - (node.lineno or 0)
                    existing.append((rel, node.name, len(node.args.args), body_lines))
    # Compare new vs existing.
    for new_file, new_name, new_args, new_lines in new_funcs:
        for old_file, old_name, old_args, old_lines in existing:
            if new_name == old_name and new_args == old_args:
                warnings.append({
                    "kind": "possible-duplicate",
                    "detail": f"同名函数 {new_name}（{new_file}）与 {old_file} 参数数相同",
                })
                break
            if old_lines > 0 and new_lines > 0 and new_args == old_args:
                ratio = min(new_lines, old_lines) / max(new_lines, old_lines)
                if ratio >= 0.8 and abs(new_lines - old_lines) <= 5:
                    warnings.append({
                        "kind": "possible-duplicate",
                        "detail": f"相似函数 {new_name}（{new_file}，{new_lines}行）与 {old_name}（{old_file}，{old_lines}行）",
                    })
                    break
    return warnings


def _module_name_for(rel_path: str, target_root: str) -> str:
    """Convert a relative file path to its Python module name.

    e.g. "src/ag2c/checks.py" with target_root "src" -> "ag2c.checks"
    """
    path = rel_path.replace("\\", "/")
    # Strip target root prefix
    if target_root and path.startswith(target_root + "/"):
        path = path[len(target_root) + 1:]
    # Strip .py extension
    if path.endswith(".py"):
        path = path[:-3]
    # Convert to module path
    return path.replace("/", ".")


def _extract_imports(file_path: Path) -> set[str]:
    """Extract all imported module names from a Python file using AST."""
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, OSError):
        return set()
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)
    return imports


def _cross_slice_warnings(manifest: Manifest, entry_slice: dict[str, Any]) -> list[dict[str, str]]:
    """Warn when changed files are imported by files outside the slice.

    This helps the agent understand the blast radius of a change: if a modified
    file is imported by many files outside the current slice, the change may
    have unintended side effects.
    """
    warnings: list[dict[str, str]] = []
    entries = entry_slice.get("entries") if isinstance(entry_slice, dict) else None
    artifacts = entries.get("paths") if isinstance(entries, dict) else None
    if not artifacts:
        return warnings
    changed_py = [
        str(item.get("path") or "")
        for item in artifacts
        if isinstance(item, dict) and str(item.get("path") or "").endswith(".py")
    ]
    if not changed_py:
        return warnings
    changed_set = set(changed_py)

    # Build module names for changed files.
    changed_modules: dict[str, str] = {}  # module_name -> file_path
    for rel in changed_py:
        # Find which target this file belongs to
        for target in manifest.targets:
            root = manifest.target_root(target.target_id)
            if (root / rel).is_file():
                mod = _module_name_for(rel, target.path)
                if mod:
                    changed_modules[mod] = rel
                break

    if not changed_modules:
        return warnings

    # Scan all Python files for imports of changed modules.
    from .index import _discover_files
    importers: dict[str, list[str]] = {mod: [] for mod in changed_modules}
    for target in manifest.targets:
        root = manifest.target_root(target.target_id)
        paths, _, _, _ = _discover_files(root, target)
        for rel in paths:
            if not rel.endswith(".py") or rel in changed_set:
                continue
            file_path = root / rel
            if not file_path.is_file():
                continue
            file_imports = _extract_imports(file_path)
            for mod in changed_modules:
                # Check if any import matches the changed module
                for imp in file_imports:
                    if imp == mod or imp.startswith(mod + ".") or mod.startswith(imp + "."):
                        importers[mod].append(rel)
                        break

    for mod, files in importers.items():
        if files:
            count = len(files)
            changed_file = changed_modules[mod]
            # Show up to 5 importers
            examples = ", ".join(files[:5])
            suffix = f" 等{count}个文件" if count > 5 else ""
            warnings.append({
                "kind": "cross-slice-dependency",
                "detail": f"{changed_file} 被切片外 {count} 个文件 import（{examples}{suffix}）",
            })
    return warnings


def _is_docs_only_change(entry_slice: dict[str, Any]) -> bool:
    """True when every changed artifact is prose documentation that cannot affect tests."""
    entries = entry_slice.get("entries") if isinstance(entry_slice, dict) else None
    artifacts = entries.get("paths") if isinstance(entries, dict) else None
    paths = [str(item.get("path") or "") for item in artifacts or [] if isinstance(item, dict)]
    paths = [path for path in paths if path]
    if not paths:
        return False
    for path in paths:
        parts = path.replace("\\", "/").split("/")
        name = parts[-1].lower()
        if Path(name).suffix in DOCS_ONLY_SUFFIXES:
            continue
        if "docs" in {part.lower() for part in parts[:-1]}:
            continue
        return False
    return True


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


def _apply_test_baseline(manifest: Manifest, checker: Checker, result: dict[str, Any], stdout: str, stderr: str) -> None:
    """Zero-regression gate for parse=unittest checkers.

    Known failures recorded in the store baseline keep the verdict green; any
    failure not in the baseline flips the result to failed. Baseline entries
    that now pass are shrunk automatically so the debt list only shrinks.
    """
    failures = parse_unittest_failures(f"{stdout}\n{stderr}")
    baseline = load_test_baseline(manifest)
    known = set(baseline.get(checker.checker_id, []))
    current = set(failures)
    new_failures = sorted(current - known)
    fixed = sorted(known - current)
    result["test_failures"] = failures
    result["baseline_failures"] = sorted(known & current)
    result["new_failures"] = new_failures
    result["fixed_failures"] = fixed
    if fixed:
        remaining = {key: value for key, value in baseline.items() if key != checker.checker_id}
        still_failing = sorted(known & current)
        if still_failing:
            remaining[checker.checker_id] = still_failing
        _save_test_baseline(manifest, remaining, actor="ag2c", reason=f"auto-shrink: {len(fixed)} baseline failures now pass")
    if result["exit_code"] == 0:
        result["status"] = "passed"
        return
    if not failures:
        result["status"] = "failed"
        result["stderr"] = str(result.get("stderr") or "") + "\ntest checker failed without parseable unittest failures; treat as a hard error"
        return
    if new_failures:
        result["status"] = "failed"
        result["stderr"] = str(result.get("stderr") or "") + "\nnew test failures not in baseline:\n- " + "\n- ".join(new_failures[:40])
        return
    result["status"] = "passed"
    result["baseline_note"] = f"{len(failures)} known failures match the recorded baseline"


def accept_test_baseline(manifest: Manifest, policy: Policy, checker_ids: list[str], *, actor: str, reason: str) -> dict[str, Any]:
    """Run parse=unittest checkers once and record their current failures as the baseline."""
    targets = [checker for checker in policy.checkers if checker.parse == "unittest"]
    if checker_ids:
        unknown = sorted(set(checker_ids) - {checker.checker_id for checker in targets})
        if unknown:
            raise AG2CError("unknown unittest checkers: " + ", ".join(unknown))
        targets = [checker for checker in targets if checker.checker_id in checker_ids]
    if not targets:
        raise AG2CError("no checkers with parse=unittest in policy; set one with govern checker --parse unittest")
    baseline = load_test_baseline(manifest)
    accepted: dict[str, Any] = {}
    for checker in targets:
        cwd = _checker_cwd(manifest, checker)
        if not cwd.is_dir():
            raise AG2CError(f"checker working directory does not exist: {cwd}")
        completed = subprocess.run(
            list(checker.command),
            cwd=cwd,
            env=git_command_env(executable=git_executable(manifest.project_root)),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=checker.timeout,
            check=False,
            shell=False,
            **hidden_process_kwargs(),
        )
        failures = parse_unittest_failures(f"{completed.stdout}\n{completed.stderr}")
        baseline[checker.checker_id] = failures
        accepted[checker.checker_id] = {"exit_code": completed.returncode, "failures": len(failures)}
    _save_test_baseline(manifest, baseline, actor=actor, reason=reason)
    return {
        "schema": TEST_BASELINE_SCHEMA,
        "actor": actor,
        "reason": reason,
        "accepted": accepted,
        "baseline": {key: len(value) for key, value in sorted(baseline.items())},
    }


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
    docs_only = _is_docs_only_change(entry_slice)
    results: list[dict[str, Any]] = []
    for checker in sorted(policy.checkers, key=lambda item: (item.stage, item.checker_id)):
        if checker.checker_id not in selected_ids:
            continue
        if docs_only and checker.always and checker.parse and not checker.implementation:
            results.append(
                {
                    "id": checker.checker_id,
                    "stage": checker.stage,
                    "target": checker.target_id,
                    "status": "skipped",
                    "exit_code": None,
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "duration_ms": 0,
                    "command": list(checker.command),
                    "implementation": checker.implementation,
                    "cwd": str(_checker_cwd(manifest, checker)),
                    "stdout": "",
                    "stderr": "",
                    "skip_reason": "docs-only diff: prose changes cannot affect the test suite",
                }
            )
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
                    **hidden_process_kwargs(),
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
        if checker.parse == "unittest" and exit_code is not None and status in {"passed", "failed"}:
            _apply_test_baseline(manifest, checker, result, stdout, stderr)
            status = str(result["status"])
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
    # Soft checks: budget, duplicate, and cross-slice dependency warnings. Never block.
    warnings: list[dict[str, str]] = []
    warnings.extend(_budget_warnings(manifest, policy, entry_slice))
    warnings.extend(_duplicate_warnings(manifest, entry_slice))
    warnings.extend(_cross_slice_warnings(manifest, entry_slice))
    if warnings:
        report["warnings"] = warnings
    # Maturity summary: count rooms at each L0-L3 level.
    maturity_counts: dict[str, int] = {}
    for card in policy.cards:
        if card.jurisdiction is not None and card.maturity:
            maturity_counts[card.maturity] = maturity_counts.get(card.maturity, 0) + 1
    if maturity_counts:
        report["maturity_summary"] = dict(sorted(maturity_counts.items()))
    if task_id is not None:
        report["task_id"] = task_id
    event = append_event(ledger_path or manifest.ledger_path, "check-run", report)
    report["ledger_sequence"] = event["sequence"]
    report["ledger_event_digest"] = event["event_digest"]
    return report
