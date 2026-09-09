"""Fixture fidelity audit (夹具保真度): gate-logic tests must run gated.

A test fixture that is more lenient than production is itself a hole: if a
test exercises gate logic while household_required=false, the household gate
is silently off and the test proves less than production demands. The
reference pattern is tests/test_sunset.py's _canary_project, which declares
household_required=true.

This meta-test scans tests/test_*.py source: any file that calls a gate
entry point must visibly opt into a gated fixture (write_project(...,
gated=True), record_census, or an explicit household_required declaration).
"""

import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent

# Gate entry points: calling one means the test exercises gate logic.
GATE_ENTRIES = ("run_checks(", "verify_task(", "enforce_households(", "finish_task(")

# Fidelity markers: the fixture visibly runs with the household gate on.
FIDELITY_MARKERS = ("gated=True", "household_required")


def _gate_test_sources() -> dict[str, str]:
    sources: dict[str, str] = {}
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        if path.name == Path(__file__).name:
            continue
        text = path.read_text(encoding="utf-8")
        if any(entry in text for entry in GATE_ENTRIES):
            sources[path.name] = text
    return sources


class FixtureFidelityTests(unittest.TestCase):
    def test_gate_tests_use_gated_fixtures(self) -> None:
        offenders = []
        for name, text in _gate_test_sources().items():
            if not any(marker in text for marker in FIDELITY_MARKERS):
                offenders.append(name)
        self.assertEqual(
            [],
            offenders,
            "tests calling gate entries (run_checks/verify_task/enforce_households/finish_task) "
            "must use a household_required=true fixture (write_project(..., gated=True) + "
            "record_census, or an explicit household_required declaration); see "
            "tests/test_sunset.py's _canary_project",
        )

    def test_meta_scan_actually_finds_gate_tests(self) -> None:
        # Guard the guard: the scan must keep finding the known gate testers,
        # otherwise a rename would silently neuter the audit above.
        found = _gate_test_sources()
        self.assertIn("test_checks.py", found)


if __name__ == "__main__":
    unittest.main()
