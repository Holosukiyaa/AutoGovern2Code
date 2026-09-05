from __future__ import annotations

from typing import Any

from .model import Policy

PRODUCT_UNDECLARED = "undeclared"
PRODUCT_BLOCKED = "blocked"
PRODUCT_INCOMPLETE = "incomplete"
PRODUCT_CHECKED = "checked"

PROCESS_CHECK_STATUSES = frozenset({"passed", "skipped"})

PRODUCT_SUMMARIES = {
    PRODUCT_UNDECLARED: "process can finish, but no product checks are declared",
    PRODUCT_BLOCKED: "stored rules are stale or conflicting; not product-checked",
    PRODUCT_INCOMPLETE: "declared product checks did not all run and pass",
    PRODUCT_CHECKED: "declared product checks passed",
}


def assess_product(
    policy: Policy,
    *,
    knowledge: list[dict[str, Any]] | None = None,
    verification: dict[str, Any] | None = None,
    census: dict[str, Any] | None = None,
) -> dict[str, Any]:
    knowledge = list(knowledge or [])
    boundary = [checker for checker in policy.checkers if checker.stage == "boundary"]
    scenario = [checker for checker in policy.checkers if checker.stage == "scenario"]
    declared = bool(policy.contracts or boundary or scenario)
    stale_rules = [
        str(item.get("id"))
        for item in knowledge
        if item.get("status") in {"stale", "conflict"}
    ]
    leftover = [
        str(item.get("id"))
        for item in (census or {}).get("households") or []
        if item.get("identity") in {"leftover", "opaque"}
    ]
    competing = [
        str(item.get("capability"))
        for item in (census or {}).get("implementations") or []
        if item.get("competing")
    ]
    results = list((verification or {}).get("checker_results") or [])
    skipped_checks = [str(item.get("id")) for item in results if item.get("status") == "skipped"]
    product_results = [item for item in results if item.get("stage") in {"boundary", "scenario"}]
    if not declared:
        status = PRODUCT_UNDECLARED
    elif stale_rules or leftover or competing:
        status = PRODUCT_BLOCKED
    elif skipped_checks:
        status = PRODUCT_INCOMPLETE
    elif product_results and all(item.get("status") == "passed" for item in product_results):
        status = PRODUCT_CHECKED
    else:
        status = PRODUCT_INCOMPLETE
    return {
        "status": status,
        "declared": declared,
        "summary": PRODUCT_SUMMARIES[status],
        "contract_count": len(policy.contracts),
        "boundary_checkers": len(boundary),
        "scenario_checkers": len(scenario),
        "stale_rules": stale_rules,
        "skipped_checks": skipped_checks,
        "leftover_households": leftover,
        "competing_capabilities": competing,
    }
