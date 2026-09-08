"""Named unittest suites for room-bound checkers.

AG2C binds floor-stage checkers to directory households: a suite runs only
when the task slice touches that room. This module is the single place that
maps suite names to test modules, so policy checker commands stay tiny:
``python -B tests/suites.py <name>``.

Suite membership is deliberate, not derived:
- fast: cheap always-on core bound at floor level as the baseline gate.
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

FAST = [
    "test_budget_dupe",
    "test_cli",
    "test_config",
    "test_dep_hint",
    "test_floor_ladder",
    "test_graph",
    "test_harnesses",
    "test_index",
    "test_knowledge",
    "test_ledger",
    "test_mcp",
    "test_notify",
    "test_review",
    "test_slicer",
    "test_suites",
    "test_sunset",
    "test_tasks",
]

SUITES = {
    "fast": FAST,
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
