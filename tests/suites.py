"""Named unittest suites for room-bound checkers.

AG2C binds floor-stage checkers to directory households: a suite runs only
when the task slice touches that room. This module is the single place that
maps suite names to test modules, so policy checker commands stay tiny:
``python -B tests/suites.py <name>``.

Suite membership is deliberate, not derived:
- fast: cheap always-on core bound at floor level as the baseline gate.
  t50 验证成本治理：fast 是真冒烟集——单模块实测 >2.5s 的一律下沉房间套件
  （2026-09-10 实测合计约 15s，预算目标 <=30s），淤积由验证预算报警看守。
- tasks / governance: heavy task-lifecycle and governance-mechanism modules
  demoted out of fast, bound to the src/ag2c and tests rooms.
- rehome / enrollment / checks / receipts / storage / gitops: slow integration
  suites bound to the src/ag2c room.
- gui: imgui tray suite bound to the src/ag2c_gui room.

When a test file appears or retires, update the mapping here; the census and
test_suites.py keep it honest.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

# 冒烟集门槛：单模块实测 <=2.5s（2026-09-10 实测，见 t50 账本）。更重的模块
# 下沉到 tasks / governance 房间套件——src/ag2c 或 tests 变动时照跑，不丢覆盖。
FAST = [
    "test_attention_gate",
    "test_auto_drill",
    "test_token",
    "test_util",
    "test_audit",
    "test_budget_dupe",
    "test_cli",
    "test_config",
    "test_dep_hint",
    "test_fixture_fidelity",
    "test_floor_ladder",
    "test_govern_pending",
    "test_graph",
    "test_green_shadow",
    "test_harnesses",
    "test_hazard",
    "test_index",
    "test_ledger",
    "test_notify",
    "test_patrol",
    "test_slicer",
    "test_suites",
]

#: 任务生命周期门禁：从 fast 下沉的重模块（test_tasks 56s / test_trunk_guard
#: 12s / test_front_back 10s），绑定 src/ag2c 与 tests 房间。
TASKS_SUITE = [
    "test_tasks",
    "test_trunk_guard",
    "test_front_back",
]

#: 治理机制：从 fast 下沉的重模块（变异/监管/MCP/证据锚/日落/知识/预算），
#: 绑定 src/ag2c 与 tests 房间。test_verify_costs 的 verify 级测试要真 enroll
#: 夹具（约 45s），按冒烟集门槛同样下沉——自家人先守自家规矩。
GOVERNANCE_SUITE = [
    "test_mutation",
    "test_mcp",
    "test_review",
    "test_anchors",
    "test_sunset",
    "test_knowledge",
    "test_budgets",
    "test_verify_costs",
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
    loader = unittest.TestLoader()
    suite = unittest.TestSuite(loader.loadTestsFromName(module) for module in SUITES[name])
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
