"""Pytest entry point: make `import bootstrap` resolve without PYTHONPATH. Every test module does `import bootstrap` first (src/ path + AG2C_DATA_ROOT isolation). unittest discovery put the tests dir on sys.path itself; pytest does not. pytest imports this conftest by file path before collecting test modules, so inserting the tests dir here keeps every `import bootstrap` working under any pytest invocation — including `ag2c verify` checker subprocesses, which inherit no PYTHONPATH. xdist workers each import this conftest, so each worker gets its own isolated data root."""
from __future__ import annotations

import sys
from pathlib import Path

TESTS_DIR = str(Path(__file__).resolve().parent)
if TESTS_DIR not in sys.path:
    sys.path.insert(0, TESTS_DIR)

import bootstrap  # noqa: E402,F401


def pytest_collection_modifyitems(items: list) -> None:
    """Pin imgui tray tests to one xdist worker, whatever the entry point. tests/suites.py already runs the gui suite without -n; this marker makes the full-run entry (`pytest tests/ -n auto --dist loadgroup`) keep the same promise: every test from the gui modules lands in the "gui" group, and a group never leaves its worker, so they execute serially. The module set is derived from SUITES["gui"] itself — suites.py stays the single source of truth, so adding a gui module cannot silently escape the serial pin."""
    import pytest

    from suites import SUITES  # tests dir is on sys.path (see above)

    gui_modules = set(SUITES["gui"])
    for item in items:
        if Path(str(item.fspath)).stem in gui_modules:
            item.add_marker(pytest.mark.xdist_group("gui"))
