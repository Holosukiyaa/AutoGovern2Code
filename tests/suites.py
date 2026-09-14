"""Named test suites for room-bound checkers. AG2C binds floor-stage checkers to directory households: a suite runs only when the task slice touches that room. This module is the single place that maps suite names to test modules, so policy checker commands stay tiny: ``python -B tests/suites.py <name>``. Execution delegates to pytest + pytest-xdist (``pip install .[test]``): unittest.TestCase suites are collected natively and distributed across CPU cores (``-n auto --dist loadgroup``). The gui and fast suites stay serial: gui because desktop HTTP tests bind a loopback server, fast so the Windows spawn tax cannot eat its per-module smoke budget. ``tests/conftest.py`` pins the gui modules to an ``xdist_group`` so full-run invocations keep them on one worker (``SUITES["gui"]`` is exactly ``test_desktop`` + ``test_dashboard``, the two pinned modules). Suite membership is deliberate, not derived: - fast: cheap always-on core bound at floor level as the baseline gate. t50 验证成本治理：fast 是真冒烟集——单模块实测 >2.5s 的一律下沉房间套件 （2026-09-10 实测合计约 15s，预算目标 <=30s），淤积由验证预算报警看守。 - tasks / governance: heavy task-lifecycle and governance-mechanism modules demoted out of fast, bound to the src/ag2c and tests rooms. - rehome / enrollment / checks / receipts / storage / gitops: slow integration suites bound to the src/ag2c room. - gui: WebView2 / desktop API suite bound to the src/ag2c_gui room. When a test file appears or retires, update the mapping here; the census and test_suites.py keep it honest."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# 冒烟集门槛：单模块实测 <=2.5s（2026-09-10 实测，见 t50 账本）。更重的模块
# 下沉到 tasks / governance 房间套件——src/ag2c 或 tests 变动时照跑，不丢覆盖。
FAST = [
    "test_attention_gate", "test_auto_drill", "test_token", "test_util", "test_audit",
    "test_budget_dupe", "test_cli", "test_config", "test_dep_hint", "test_fixture_fidelity",
    "test_floor_ladder", "test_govern_pending", "test_graph", "test_green_shadow", "test_harnesses",
    "test_index", "test_ledger", "test_notify", "test_patrol", "test_slicer", "test_suites",
]

#: 任务生命周期门禁：从 fast 下沉的重模块（test_tasks 56s / test_trunk_guard
#: 12s / test_front_back 10s），绑定 src/ag2c 与 tests 房间。
TASKS_SUITE = [
    "test_tasks", "test_trunk_guard", "test_front_back",
    "test_portrait_amend", "test_scheduler", "test_coordinates",
]

#: 治理机制：从 fast 下沉的重模块（变异/监管/MCP/证据锚/日落/知识/预算），
#: 绑定 src/ag2c 与 tests 房间。test_verify_costs 的 verify 级测试要真 enroll
#: 夹具（约 45s），按冒烟集门槛同样下沉——自家人先守自家规矩。
#: test_hazard 于 2026-09-11 下沉：4.4 的 git 夹具测试（GuardHeartbeat/
#: UngovernedCommit）把模块养到实测 11.1s，超冒烟集门槛 4 倍。
GOVERNANCE_SUITE = [
    "test_mutation", "test_mcp", "test_review", "test_anchors", "test_sunset",
    "test_knowledge", "test_census_hardening", "test_budgets", "test_verify_costs", "test_hazard",
    # t59：文件粒度户口 + 删除门，实测 10.8s（git 夹具 + 普查），超冒烟集门槛下沉。
    "test_file_grain", "test_flatten",
]

SUITES = {
    "fast": FAST,
    "tasks": TASKS_SUITE,
    "governance": GOVERNANCE_SUITE,
    "rehome": ["test_rehome"],
    "enrollment": ["test_enrollment"],
    "checks": ["test_checks"],
    "receipts": ["test_receipts"],
    "storage": ["test_storage"],
    "gitops": ["test_gitops"],
    "gui": ["test_desktop", "test_dashboard"],
}


def main(argv: list[str]) -> int:
    tests_dir = Path(__file__).resolve().parent
    if str(tests_dir) not in sys.path:
        sys.path.insert(0, str(tests_dir))
    args = [arg for arg in argv[1:] if arg]
    if not args or args[0] in {"-h", "--help"}:
        print("usage: python -B tests/suites.py <suite> [--list]")
        print("suites:", ", ".join(sorted(SUITES)))
        return 2
    name = args[0]
    if name not in SUITES:
        print(f"unknown suite: {name}; expected one of {', '.join(sorted(SUITES))}", file=sys.stderr)
        return 2
    if "--list" in args:
        for module in SUITES[name]:
            print(module)
        return 0
    try:
        import pytest  # noqa: F401
        import xdist  # noqa: F401
    except ImportError:
        print("pytest and pytest-xdist are required: pip install .[test]", file=sys.stderr)
        return 2
    tests_dir = Path(__file__).resolve().parent
    files = [str(tests_dir / f"{module}.py") for module in SUITES[name]]
    cmd = [sys.executable, "-X", "utf8", "-B", "-m", "pytest", "-q", *files]
    if name not in {"gui", "fast"}:
        # desktop HTTP tests bind a loopback server; the fast smoke set stays
        # serial so spawn tax cannot eat its per-module budget. Every other
        # suite parallelizes. loadgroup honours the xdist_group("gui") pin
        # from tests/conftest.py, so the full-run entry keeps gui serial too.
        cmd += ["-n", "auto", "--dist", "loadgroup"]
    return subprocess.call(cmd, cwd=str(tests_dir.parent))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
