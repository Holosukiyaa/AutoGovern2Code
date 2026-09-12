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
from .util import digest_file, digest_json, hidden_process_kwargs

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


# Derived-density ceilings: when a room sets only budget_lines, the chars and
# AST-node budgets are derived from it. Normal Python averages ~30-60 chars/line
# and ~5-10 AST nodes/line; the derived ceilings are deliberately generous so
# only deliberate density-gaming (200-char lines, semicolon-packed statements)
# trips them. Explicit budget_chars / budget_ast_nodes on the card override.
DERIVED_CHARS_PER_LINE = 160
DERIVED_AST_NODES_PER_LINE = 15


def _room_code_measurements(manifest: Manifest, item: dict[str, Any]) -> dict[str, int]:
    """Measure a census household's code in three dimensions: lines, chars, AST nodes.

    All three dimensions are measured from real file contents. (The census
    ``code_count`` is a code-FILE count, not a line count — do not trust it
    for the lines dimension.)
    """
    lines = 0
    chars = 0
    ast_nodes = 0
    for entry in item.get("files") or []:
        if not isinstance(entry, str) or ":" not in entry:
            continue
        target_id, rel = entry.split(":", 1)
        try:
            root = manifest.target_root(target_id)
        except StopIteration:
            continue
        path = root / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines += len(text.splitlines())
        chars += len(text)
        if rel.endswith(".py"):
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            ast_nodes += sum(1 for _ in ast.walk(tree))
    return {"lines": lines, "chars": chars, "ast_nodes": ast_nodes}


def _budget_warnings(manifest: Manifest, policy: Policy, entry_slice: dict[str, Any]) -> list[dict[str, str]]:
    """Soft budget, multi-dimensional: lines + chars + AST nodes. Never blocks.

    Anti-gaming (钉子厂): a room that only declares budget_lines still gets
    chars/AST ceilings derived from it, so packing code dense to stay under the
    line budget trips the other two dimensions.

    动态预算（2026-09-10）：行预算读有效值——policy 显式优先，否则动态仓
    （budgets.py 按普查实测自动锚定、只紧不松）。房间不用人算预算也有护栏。
    """
    warnings: list[dict[str, str]] = []
    from .budgets import effective_budget_lines
    from .households import census_report
    try:
        report = census_report(manifest, policy)
    except Exception:
        return warnings
    for item in report.get("households") or []:
        if not isinstance(item, dict):
            continue
        try:
            card = policy.card(str(item.get("id") or ""))
        except StopIteration:
            continue
        if card is None:
            continue
        budget_lines = effective_budget_lines(manifest, card)
        budget_chars = card.budget_chars or (budget_lines * DERIVED_CHARS_PER_LINE if budget_lines else 0)
        budget_ast = card.budget_ast_nodes or (budget_lines * DERIVED_AST_NODES_PER_LINE if budget_lines else 0)
        if budget_lines <= 0 and budget_chars <= 0 and budget_ast <= 0:
            continue
        # 预算来源：人工定价（policy 显式字段）vs 动态仓快照。派生维度
        # （chars/ast 从行预算推算）跟随其父预算的来源。该标记决定 9.7
        # 硬化分流——动态快照注定随房间自然增长过期，不该硬化成门。
        lines_source = "explicit" if int(card.budget_lines or 0) > 0 else "dynamic"
        chars_source = "explicit" if int(card.budget_chars or 0) > 0 else lines_source
        ast_source = "explicit" if int(card.budget_ast_nodes or 0) > 0 else lines_source
        room = str(item.get("id") or "")
        measured = _room_code_measurements(manifest, item)
        dimensions = (
            ("lines", measured["lines"], budget_lines, "行", lines_source),
            ("chars", measured["chars"], budget_chars, "字符", chars_source),
            ("ast_nodes", measured["ast_nodes"], budget_ast, "AST 节点", ast_source),
        )
        for dimension, actual, budget, unit, source in dimensions:
            if budget > 0 and actual > budget:
                warnings.append({
                    "kind": "over-budget",
                    "room": room,
                    "dimension": dimension,
                    "key": f"{room}:{dimension}",
                    "detail": f"{actual} {unit}，预算 {budget}（超出 {actual - budget}，维度 {dimension}）",
                    "budget_source": source,
                })
    return warnings


_UNITTEST_CONVENTION_METHODS = frozenset({
    "setUp", "tearDown", "setUpClass", "tearDownClass", "setUpModule", "tearDownModule",
})

# Entry-point names carry no semantic signal: every CLI module has a
# ``main(argv)``, so same-name-same-arity matches on them are noise by
# definition. 9.7 escalation hardened this false positive into gate blocks
# twice within a day (tests/suites.py:main, src/ag2c/cli.py:main).
_NON_SIGNALING_NAMES = frozenset({"main"})


def _head_function_signatures(root: Path, rel: str) -> set[tuple[str, int, tuple[tuple[str, int], ...]]]:
    """该文件在 git HEAD 版本里已有的函数签名（名字/参数数/结构）。

    用于区分"本 diff 新增或改动的函数"与"文件里原本就有的函数"——后者不该
    因为文件被碰过就重复报警（9.7 升级机制会把这种重复报警固化成门禁拦截）。
    非 git 上下文（单元测试的裸临时目录）返回空集，退化为全部视为新函数。
    """
    try:
        from .gitops import git

        raw = git(root, "show", f"HEAD:{rel}", binary=True)
    except Exception:
        return set()
    if not isinstance(raw, bytes):
        return set()
    try:
        tree = ast.parse(raw.decode("utf-8", errors="replace"))
    except SyntaxError:
        return set()
    return {
        (node.name, len(node.args.args), _function_shape(node))
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


#: 函数特征元组：(name, arity, body_lines, shape)。配对规则的输入单元。
FunctionSig = tuple[str, int, int, tuple[tuple[str, int], ...]]


def duplicate_match(new: FunctionSig, old: FunctionSig) -> str | None:
    """现行查重配对规则（单一事实来源）：diff 警告与危房全仓扫描共用。

    返回 "同名"（重实现助手）/ "相似"（复制粘贴）/ None。规则与精度军规见
    _duplicate_warnings 上方注释——任何校准只改这里，两处消费者同步生效。
    """
    new_name, new_args, new_lines, new_shape = new
    old_name, old_args, old_lines, old_shape = old
    if new_args != old_args:
        return None
    if _shape_similarity(new_shape, old_shape) < 0.9:
        return None
    if new_name == old_name and min(new_lines, old_lines) >= 4:
        return "同名"
    if (
        new_lines >= 8
        and old_lines >= 8
        and min(new_lines, old_lines) / max(new_lines, old_lines) >= 0.8
    ):
        return "相似"
    return None


def scan_duplicate_pairs(manifest: Manifest) -> list[dict[str, Any]]:
    """全仓实时查重：现行配对规则对所有受治理 .py 函数两两配对。

    与 _duplicate_warnings 的 diff 触发互补：那个管"新写的代码别抄"，这个管
    "存量里还有哪些真重复"——危房名单的拆迁队列用这个，warning-history 里的
    化石记录（旧探测器残留、规则校准后不再复现）自然不再出现。
    """
    functions: list[tuple[str, FunctionSig]] = []  # (rel, sig)
    from .index import _discover_files

    for target in manifest.targets:
        root = manifest.target_root(target.target_id)
        paths, _, _, _ = _discover_files(root, target)
        for rel in paths:
            if not rel.endswith(".py"):
                continue
            path = root / rel
            if not path.is_file():
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except (SyntaxError, OSError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name in _UNITTEST_CONVENTION_METHODS or node.name in _NON_SIGNALING_NAMES:
                        continue
                    body_lines = (node.end_lineno or 0) - (node.lineno or 0)
                    functions.append((rel, (node.name, len(node.args.args), body_lines, _function_shape(node))))
    pairs: list[dict[str, Any]] = []
    for index, (new_file, new_sig) in enumerate(functions):
        for old_file, old_sig in functions[index + 1 :]:
            match = duplicate_match(new_sig, old_sig)
            if match is None:
                continue
            pairs.append({
                "file": new_file,
                "name": new_sig[0],
                "lines": new_sig[2],
                "other_file": old_file,
                "other_name": old_sig[0],
                "other_lines": old_sig[2],
                "match": match,
            })
    return pairs


def _function_shape(node: ast.AST) -> tuple[tuple[str, int], ...]:
    """Sorted AST node-type multiset for a function body — a structural fingerprint."""
    counts: dict[str, int] = {}
    for child in ast.walk(node):
        name = type(child).__name__
        counts[name] = counts.get(name, 0) + 1
    return tuple(sorted(counts.items()))


def _shape_similarity(a: tuple[tuple[str, int], ...], b: tuple[tuple[str, int], ...]) -> float:
    """Multiset Jaccard similarity between two shape fingerprints."""
    if not a or not b:
        return 0.0
    counts_a, counts_b = dict(a), dict(b)
    keys = set(counts_a) | set(counts_b)
    intersection = sum(min(counts_a.get(k, 0), counts_b.get(k, 0)) for k in keys)
    union = sum(max(counts_a.get(k, 0), counts_b.get(k, 0)) for k in keys)
    return intersection / union if union else 0.0


# --- 9.12: baseline decreasing pressure (债务上限: the baseline only shrinks) ---
#
# The test baseline is a debt ledger. baseline_debt() compares the live total
# against a ratcheting target stored in state/baseline-target.json: the first
# observation establishes the ceiling, and the target only ever ratchets DOWN
# when reality improves. New debt pushes total above target -> over=True, which
# the dashboard surfaces as an alert. Advisory only; never blocks verify.
BASELINE_TARGET_SCHEMA = "ag2c.baseline-target.v1"


def _baseline_target_path(manifest: Manifest) -> Path:
    return manifest.state_dir / "baseline-target.json"


def baseline_debt(manifest: Manifest) -> dict[str, Any]:
    """Return {"total", "target", "over"} for the test baseline, ratcheting the target down."""
    baseline = load_test_baseline(manifest)
    total = sum(len(failures) for failures in baseline.values())
    path = _baseline_target_path(manifest)
    target: int | None = None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and raw.get("schema") == BASELINE_TARGET_SCHEMA:
            target = max(0, int(raw.get("target")))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        target = None
    changed = target is None
    if target is None:
        target = total  # first observation establishes the ceiling
    if total < target:
        target = total  # ratchet down: paid debt lowers the ceiling permanently
        changed = True
    if changed:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "schema": BASELINE_TARGET_SCHEMA,
                        "target": target,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        except OSError:
            pass
    return {"total": total, "target": target, "over": total > target}


# --- 9.7: warning auto-escalation (泰坦尼克: ignored warnings must harden) ---
#
# Every warning carries a stable "key". Appearances are counted in
# state/warning-history.json; a defect-class warning that appears for the Nth
# time while still present hardens into a gate block. Informational hints
# (cross-slice-dependency) describe blast radius, not defects — a hub module
# cannot "fix" being imported — so they are tracked but never escalate.
# Dynamic-budget over-budget warnings (budget_source=dynamic) are tracked but
# never escalate either: a system snapshot going stale is not defiance.
#
# 计数语义（t25 调优）："无视"按任务计，不按 verify 运行次数计——同一任务
# 内重试 verify（修无关问题、普查过期、换行符事故）不等于无视警告。调用方
# 传 count_key（verify 传 task_id）时按 key 去重；不传 count_key 的调用
# （CLI check / 金丝雀 / CI 重放）只读不写——金丝雀跑的是变异代码，其警告
# 不应污染历史。
WARNING_ESCALATION_THRESHOLD = 3
WARNING_HISTORY_SCHEMA = "ag2c.warning-history.v1"
ESCALATABLE_KINDS = frozenset({"over-budget", "possible-duplicate", "coordinate-reconciliation"})
_MAX_COUNT_KEYS = 50


def _escalatable(warning: dict[str, str]) -> bool:
    """缺陷类警告才硬化；动态预算的超标警告永远只警告、不成门。

    动态预算是系统按普查实测拍的快照（budgets.py 棘轮只紧不松），增长型
    房间（tests/docs）自然长个儿必然顶破它——快照过期不该硬化成门，否则
    等于惩罚增长本身（2026-09-11 tests 房间：覆盖率增长 338 行，第三个
    携带该警告的任务被门拦住）。人工定价（policy 显式 budget_lines）的
    超标才升级对峙——价格是人定的，不符就该重新谈。budget_source 缺失
    的警告（旧历史、verify_costs 秒预算）按人工处理，维持既有行为。
    """
    if str(warning.get("kind") or "") not in ESCALATABLE_KINDS:
        return False
    if warning.get("kind") == "over-budget" and str(warning.get("budget_source") or "") == "dynamic":
        return False
    return True


def _warning_history_path(manifest: Manifest) -> Path:
    return manifest.state_dir / "warning-history.json"


def _warning_fingerprint(warning: dict[str, str]) -> str:
    return digest_json({"kind": warning.get("kind"), "key": warning.get("key") or warning.get("detail")})


def _load_warning_history(manifest: Manifest) -> dict[str, Any]:
    path = _warning_history_path(manifest)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema": WARNING_HISTORY_SCHEMA, "warnings": {}}
    if not isinstance(raw, dict) or raw.get("schema") != WARNING_HISTORY_SCHEMA:
        return {"schema": WARNING_HISTORY_SCHEMA, "warnings": {}}
    if not isinstance(raw.get("warnings"), dict):
        raw["warnings"] = {}
    return raw


def _record_warnings_and_find_escalated(
    manifest: Manifest, warnings: list[dict[str, str]], count_key: str | None = None
) -> list[dict[str, Any]]:
    """Persist this run's warning appearances; return the ones that just hardened.

    A warning escalates when its cumulative appearance count reaches
    WARNING_ESCALATION_THRESHOLD and it is still present in this run. A warning
    that disappears stops blocking; its count is kept, so a recurring problem
    does not reset the clock.

    count_key（verify 传 task_id）按任务去重：同一任务重试多次只计一次。
    count_key 为 None 的调用（CLI check / 金丝雀 / CI 重放）只读不写——
    仍然依据既有计数报告已升级的警告，但不产生新计数。
    """
    history = _load_warning_history(manifest)
    store = history["warnings"]
    now = datetime.now(timezone.utc).isoformat()
    escalated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for warning in warnings:
        fingerprint = _warning_fingerprint(warning)
        if fingerprint in seen:
            continue  # one logical warning counts once per run, however many instances
        seen.add(fingerprint)
        entry = store.get(fingerprint)
        if not isinstance(entry, dict):
            entry = {"kind": warning.get("kind"), "key": warning.get("key"), "count": 0, "first_seen": now}
            if count_key is not None:
                store[fingerprint] = entry
        if count_key is not None:
            count_keys = entry.setdefault("count_keys", [])
            if count_key not in count_keys:
                entry["count"] = int(entry.get("count") or 0) + 1
                count_keys.append(count_key)
                del count_keys[:-_MAX_COUNT_KEYS]  # 只留最近一批 key；count 单调不回退
            entry["last_seen"] = now
            entry["detail"] = str(warning.get("detail") or "")
        if _escalatable(warning) and int(entry.get("count") or 0) >= WARNING_ESCALATION_THRESHOLD:
            escalated.append({**warning, "count": entry["count"]})
    if count_key is not None:
        try:
            path = _warning_history_path(manifest)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError:
            return []  # best-effort: without persistence there is no memory, so no escalation
    return escalated


def dismiss_warning(manifest: Manifest, key: str, *, actor: str, reason: str) -> dict[str, Any]:
    """撤销一条警告的累计计数——升级门的合法出口，语义是"已知情"，不是"已修复"。

    删除条目而非清零：账本事件承载审计（key、被删时的计数、actor、reason），
    历史文件保持"当前活着的警告"语义。dismissal 后同 key 从零重新计数，
    反复出现的问题会再次升级——这是特性。先落账本再写历史：append_event
    失败时 warning-history 磁盘字节不变。
    """
    from .ledger import append_event

    key = str(key or "").strip()
    if not key:
        raise AG2CError("warning-dismiss requires a --key")
    history = _load_warning_history(manifest)
    store = history.get("warnings", {})
    # 历史以 fingerprint（kind+key 的 digest）为键；用户面对的是升级门报错里
    # 的 key 字段（如 check.suite-enrollment:seconds），按条目内 key 匹配。
    matches = {fp: entry for fp, entry in store.items() if isinstance(entry, dict) and str(entry.get("key") or "") == key}
    if not matches:
        raise AG2CError(f"unknown warning key: {key!r}（warning-history 中不存在）")
    dismissed = [
        {"kind": str(entry.get("kind") or ""), "count": int(entry.get("count") or 0)}
        for entry in matches.values()
    ]
    event = append_event(
        manifest.ledger_path,
        "warning-dismiss",
        {"key": key, "dismissed": dismissed, "actor": actor, "reason": reason},
    )
    for fingerprint in matches:
        store.pop(fingerprint, None)
    try:
        _warning_history_path(manifest).write_text(
            json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except OSError as exc:
        raise AG2CError(f"warning-history 写回失败：{exc}") from exc
    return {"key": key, "dismissed": dismissed, "ledger_event_digest": event.get("event_digest")}


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

from .check_run import run_checks, _duplicate_warnings, _cross_slice_warnings
