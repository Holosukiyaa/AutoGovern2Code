from __future__ import annotations

from pathlib import Path
from typing import Any

from .model import Checker, Policy

PRODUCT_UNDECLARED = "undeclared"
PRODUCT_BLOCKED = "blocked"
PRODUCT_INCOMPLETE = "incomplete"
PRODUCT_CHECKED = "checked"

GROWTH_UNSPLIT = "unsplit"
GROWTH_SLICED = "sliced"

PROCESS_CHECK_STATUSES = frozenset({"passed", "skipped"})

PRODUCT_SUMMARIES = {
    PRODUCT_UNDECLARED: "process can finish, but no product checks are declared",
    PRODUCT_BLOCKED: "stored rules are stale or conflicting; not product-checked",
    PRODUCT_INCOMPLETE: "declared product checks did not all run and pass",
    PRODUCT_CHECKED: "declared product checks passed",
}

GROWTH_SUMMARIES = {
    GROWTH_UNSPLIT: "card map may be structured; product tests are still one blob",
    GROWTH_SLICED: "a knowledge-bound product test uses a command distinct from the always-on blob",
}


def _is_diff_check(checker: Checker) -> bool:
    command = list(checker.command)
    return len(command) >= 2 and command[0] == "git" and command[1] == "diff" and "--check" in command


def assess_verification_growth(policy: Policy) -> dict[str, Any]:
    """Map coverage.level is not verification maturity.

    structured means rooms/cards exist. sliced means a knowledge card owns a
    non-always product test whose command is not the always-on blob.
    """
    tests = [checker for checker in policy.checkers if not _is_diff_check(checker)]
    knowledge_bound = {
        str(checker_id)
        for card in policy.cards
        if card.card_type == "knowledge"
        for checker_id in card.checkers
    }
    always_commands = {tuple(checker.command) for checker in tests if checker.always}
    sliced_ids = [
        checker.checker_id
        for checker in tests
        if not checker.always
        and checker.checker_id in knowledge_bound
        and (not always_commands or tuple(checker.command) not in always_commands)
    ]
    if sliced_ids:
        status = GROWTH_SLICED
        reason = "room-bound-distinct"
    elif not tests:
        status = GROWTH_UNSPLIT
        reason = "none"
    elif len({tuple(checker.command) for checker in tests}) <= 1:
        status = GROWTH_UNSPLIT
        reason = "same-command-blob"
    else:
        status = GROWTH_UNSPLIT
        reason = "not-room-bound"
    return {
        "status": status,
        "summary": GROWTH_SUMMARIES[status],
        "reason": reason,
        "product_test_count": len(tests),
        "room_bound_distinct": sliced_ids,
    }


def coverage_view(policy: Policy, *, project_root: Path | None = None) -> dict[str, Any]:
    from .seed import assess_seed

    growth = assess_verification_growth(policy)
    seed = assess_seed(policy, project_root=project_root)
    return {
        "level": policy.coverage.level,
        "strategy": policy.coverage.strategy,
        "managed_by": policy.coverage.managed_by,
        "areas": list(policy.coverage.areas),
        "area_count": len([card for card in policy.cards if card.card_type == "floor"]),
        "checker_count": len(policy.checkers),
        "contract_count": len(policy.contracts),
        "verification_growth": growth["status"],
        "verification_growth_summary": growth["summary"],
        "verification_growth_reason": growth["reason"],
        "seed": seed,
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
