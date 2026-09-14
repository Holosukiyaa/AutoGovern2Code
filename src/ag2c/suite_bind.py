"""Map a changed test file to the one suite that contains it.

tests/ is not the whole product tree. A tests-only household therefore must
not drag every suite checker. Keep DEFAULT_SUITES identical to tests/suites.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

FULL_SUITE_SWITCH_CLOSED = (
    "全量验收开关已关闭。验证只跑改动文件所在房间的套件；"
    "tests/ 里一个文件不等于覆盖全部产品目录。"
    "要跑某套件，改动必须落在该套件对应的产品目录或该套件的测试模块。"
)

# Keep identical to tests/suites.py SUITES (test_suites.SuiteMappingTests checks).
DEFAULT_SUITES: dict[str, list[str]] = {
    "fast": [
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
        "test_index",
        "test_ledger",
        "test_notify",
        "test_patrol",
        "test_slicer",
        "test_suites",
    ],
    "tasks": [
        "test_tasks",
        "test_trunk_guard",
        "test_front_back",
        "test_portrait_amend",
        "test_scheduler",
        "test_coordinates",
    ],
    "governance": [
        "test_mutation",
        "test_mcp",
        "test_review",
        "test_anchors",
        "test_sunset",
        "test_knowledge",
        "test_census_hardening",
        "test_budgets",
        "test_verify_costs",
        "test_hazard",
        "test_file_grain",
        "test_flatten",
    ],
    "rehome": ["test_rehome"],
    "enrollment": ["test_enrollment"],
    "checks": ["test_checks"],
    "receipts": ["test_receipts"],
    "storage": ["test_storage"],
    "gitops": ["test_gitops"],
    "gui": ["test_desktop", "test_dashboard"],
}

SUITE_TO_CHECKER: dict[str, str] = {
    "tasks": "check.suite-tasks",
    "governance": "check.suite-governance",
    "rehome": "check.suite-rehome",
    "enrollment": "check.suite-enrollment",
    "checks": "check.suite-checks",
    "receipts": "check.suite-receipts",
    "storage": "check.suite-storage",
    "gitops": "check.suite-gitops",
    "gui": "check.suite-gui",
}


def test_module_name(path: str) -> str | None:
    rel = str(path).replace("\\", "/").split(":", 1)[-1].lstrip("./")
    if not rel.startswith("tests/") or not rel.endswith(".py"):
        return None
    name = Path(rel).stem
    return name if name.startswith("test_") else None


def suite_checker_ids_for_paths(
    paths: Iterable[str],
    *,
    suites: dict[str, list[str]] | None = None,
) -> set[str]:
    modules = {test_module_name(path) for path in paths}
    modules.discard(None)
    table = suites or DEFAULT_SUITES
    found: set[str] = set()
    for suite_name, members in table.items():
        checker = SUITE_TO_CHECKER.get(suite_name)
        if not checker:
            continue
        if modules.intersection(members):
            found.add(checker)
    return found


def is_tests_tree_includes(includes: Iterable[str]) -> bool:
    patterns = [str(item).replace("\\", "/").lstrip("./") for item in includes]
    return bool(patterns) and all(item == "tests" or item.startswith("tests/") for item in patterns)


def is_tests_tree_card(card: Any) -> bool:
    includes: list[str] = []
    for scope in getattr(card, "scopes", ()) or ():
        includes.extend(getattr(scope, "includes", None) or getattr(scope, "include", None) or [])
    return is_tests_tree_includes(includes)
