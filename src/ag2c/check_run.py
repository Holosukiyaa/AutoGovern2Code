"""Extracted by flatten-split."""
from __future__ import annotations
import ast
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from .errors import AG2CError
from .gitops import git_command_env, git_executable
from .index import index_path, summary as index_summary, verify_freshness
from .ledger import append_event
from .model import Checker, Manifest, Policy
from .util import digest_file, hidden_process_kwargs
from .checks import _NON_SIGNALING_NAMES, _UNITTEST_CONVENTION_METHODS, _apply_test_baseline, _budget_warnings, _checker_cwd, _clip, _extract_imports, _function_shape, _head_function_signatures, _is_docs_only_change, _module_name_for, _record_warnings_and_find_escalated, _skip_reason, _stage_acceptance, baseline_debt, duplicate_match, environment_snapshot

def _duplicate_warnings(manifest: Manifest, entry_slice: dict[str, Any]) -> list[dict[str, str]]:
    """Soft duplicate detection: warn when new functions look like existing ones.

    Uses AST to extract function names + body line counts. A function is only
    considered when this diff added or modified it (vs git HEAD); it is flagged
    when an existing function has the same name + arity + substantial body, or
    a substantial body with a near-identical AST node-type multiset.
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
    # Collect all functions from changed files. unittest convention methods
    # (setUp/tearDown/...) are idiomatic scaffolding, not duplication — and
    # since 9.7 warnings can harden into gate blocks, detector noise must not.
    new_funcs: list[tuple[str, str, int, int, tuple[tuple[str, int], ...]]] = []
    for rel in changed_py:
        path = manifest.project_root / rel
        if not path.is_file():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        preexisting = _head_function_signatures(manifest.project_root, rel)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in _UNITTEST_CONVENTION_METHODS or node.name in _NON_SIGNALING_NAMES:
                    continue
                signature = (node.name, len(node.args.args), _function_shape(node))
                if signature in preexisting:
                    continue  # 本 diff 没动它——存量重复不由碰过它的任务背锅
                body_lines = (node.end_lineno or 0) - (node.lineno or 0)
                new_funcs.append((rel, node.name, len(node.args.args), body_lines, _function_shape(node)))
    if not new_funcs:
        return warnings
    # Collect existing functions from all governed Python files.
    from .index import _discover_files
    existing: list[tuple[str, str, int, int, tuple[tuple[str, int], ...]]] = []
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
                    if node.name in _UNITTEST_CONVENTION_METHODS or node.name in _NON_SIGNALING_NAMES:
                        continue
                    body_lines = (node.end_lineno or 0) - (node.lineno or 0)
                    existing.append((rel, node.name, len(node.args.args), body_lines, _function_shape(node)))
    # Compare new vs existing. Deliberately high-precision, because 9.7
    # escalation hardens repeated warnings into gate blocks:
    # - same name + same arity + near-identical body shape (re-implemented
    #   helper), with a 4-line floor — below that, shape is meaningless;
    # - or a SUBSTANTIAL body (>=8 lines) with a near-identical AST node-type
    #   multiset under any name (copy-paste).
    # Name+arity ALONE was noise: conventional helper names (main, _git,
    # _clip) collide across modules without shared code, and escalation
    # hardened four such false positives into gate blocks within one day.
    for new_file, new_name, new_args, new_lines, new_shape in new_funcs:
        if new_name in _NON_SIGNALING_NAMES:
            continue
        for old in existing:
            match = duplicate_match(
                (new_name, new_args, new_lines, new_shape), (old[1], old[2], old[3], old[4])
            )
            if match == "同名":
                warnings.append({
                    "kind": "possible-duplicate",
                    "key": f"{new_file}:{new_name}",
                    "detail": f"同名函数 {new_name}（{new_file}）与 {old[0]} 参数数与结构均一致",
                })
                break
            if match == "相似":
                warnings.append({
                    "kind": "possible-duplicate",
                    "key": f"{new_file}:{new_name}",
                    "detail": f"相似函数 {new_name}（{new_file}，{new_lines}行）与 {old[1]}（{old[0]}，{old[3]}行）结构高度一致",
                })
                break
    return warnings

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
                "key": changed_file,
                "detail": f"{changed_file} 被切片外 {count} 个文件 import（{examples}{suffix}）",
            })
    return warnings

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
    ordered = [
        checker
        for checker in sorted(policy.checkers, key=lambda item: (item.stage, item.checker_id))
        if checker.checker_id in selected_ids
    ]
    results: list[dict[str, Any] | None] = [None] * len(ordered)
    runnable: list[tuple[int, Checker]] = []
    for index, checker in enumerate(ordered):
        if docs_only and checker.always and checker.parse and not checker.implementation:
            results[index] = (
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
        runnable.append((index, checker))

    def _execute(checker: Checker) -> tuple[dict[str, Any], str, str]:
        """跑一个 checker 子进程；只读共享状态，可并行。基线写回在主线程串行做。"""
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
                # 硬杀线单源派生（P0 2026-09-10）：动态秒预算×3×并行度，无锚定回退
                # 静态 timeout×并行度。parallelism 是 _execute 的形参，此处直接传入。
                from .verify_costs import effective_timeout_seconds

                timeout_seconds = effective_timeout_seconds(manifest, checker, parallelism=parallelism)
                completed = subprocess.run(
                    list(checker.command),
                    cwd=cwd,
                    env=env,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout_seconds,
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
                stderr = f"checker timed out after {timeout_seconds:.0f} seconds"
            except OSError as exc:
                stderr = f"cannot execute checker: {exc}"
            except Exception as exc:  # 并行模式下单个 checker 异常不能拖垮整轮
                stderr = f"checker crashed: {exc}"
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
        return result, stdout, stderr

    parallelism = max(1, int(getattr(policy, "checker_parallelism", 1) or 1))
    if parallelism > 1 and len(runnable) > 1:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=min(parallelism, len(runnable))) as pool:
            executed = list(pool.map(lambda pair: _execute(pair[1]), runnable))
    else:
        executed = [_execute(checker) for _, checker in runnable]
    for (index, checker), (result, stdout, stderr) in zip(runnable, executed):
        # 基线读写共享存储，必须主线程串行；只有子进程执行并行。
        if checker.parse == "unittest" and result["exit_code"] is not None and result["status"] in {"passed", "failed"}:
            _apply_test_baseline(manifest, checker, result, stdout, stderr)
        results[index] = result
    results = [item for item in results if item is not None]
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
    from .softcap import file_soft_cap_warnings

    warnings.extend(file_soft_cap_warnings(manifest))
    # 证据锚：切片内知识卡的 provides 必须锚定 references 的真实顶层符号。
    # 存量迁移期——进 warning-history 追踪但刻意不加入 ESCALATABLE_KINDS，永不升级阻断。
    from .anchors import provides_anchor_warnings

    slice_card_ids = {str(card.get("id")) for card in entry_slice.get("cards", []) if isinstance(card, dict)}
    warnings.extend(provides_anchor_warnings(manifest, policy, card_ids=slice_card_ids))
    # t50 验证成本治理：checker 耗时超动态/显式秒预算时报警（over-budget 种类，
    # 自动获得 9.7 升级与危房名单通道）。无预算仓或无显式预算时不报警。
    from .verify_costs import verify_budget_warnings

    warnings.extend(verify_budget_warnings(manifest, policy, results))
    if warnings:
        report["warnings"] = warnings
    # 9.7: count appearances; defect-class warnings harden into gate blocks.
    escalated = _record_warnings_and_find_escalated(manifest, warnings, count_key=task_id)
    if escalated:
        report["escalated_warnings"] = escalated
    # 9.12: baseline debt vs ratcheting target (advisory; the dashboard alerts).
    report["baseline_debt"] = baseline_debt(manifest)
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
    if escalated:
        raise AG2CError(
            "warnings escalated to gate after repeated ignores (警告自动升级):\n- "
            + "\n- ".join(
                f'{item.get("kind")}[{item.get("key")}] 已出现 {item.get("count")} 次: {item.get("detail")}'
                for item in escalated
            )
        )
    return report
