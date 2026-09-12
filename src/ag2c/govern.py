from __future__ import annotations
from .govern_support import (
    BOUNDARY_HINTS,
    PENDING_FILENAME,
    _atomic_json,
    _card_include_roots,
    _floor_for_path,
    _include_roots_overlap,
    _jurisdiction_include_roots,
    _now,
    _read_json,
)

from pathlib import Path
from typing import Any

from .config import discover_manifest, load_manifest, load_policy
from .errors import AG2CError, ConfigurationError
from ag2c_gui.graph import KNOWLEDGE_TITLE_LIMIT, clip_knowledge_title
from .gitops import repository_root
from .index import build_index, index_path
from .knowledge import knowledge_status, sync_knowledge
from .ledger import append_event
from .model import Manifest
from .util import normalize_artifact_path


PENDING_TITLES = {
    "unowned-area": "新目录还没有登记",
    "new-document": "新文档还没有入库",
    "changed-document": "文档有变化，需要更新 Knowledge",
    "stale-knowledge": "Knowledge 已过期",
    "assertion-conflict": "文档要点和记录冲突",
    "new-interface": "检测到新的公开界面",
    "undeclared-product": "还没有产品验收",
    "census-review-required": "目录户口需要普查",
    "tighten-or-renew": "开工区结构已撑破，需要收紧或续期",
    "opaque-household": "户口自称说清，但仍是黑盒",
    "fake-child": "子户口没有落在父范围的真子集上",
}
PENDING_HINTS = {
    "add-or-expand-floor": "补目录归属",
    "add-knowledge": "加入 Knowledge",
    "add-or-update-knowledge": "更新 Knowledge",
    "sync-or-update-knowledge": "同步 Knowledge",
    "review-then-sync-knowledge": "核对要点后再同步",
    "add-boundary": "登记公开界面，并补上对应检查",
    "declare-product-checks": "补上要验的能力和对应检查",
    "review-directory-census": "记录目录普查，不能把黑盒写成说清",
    "tighten-or-renew-exploring": "收紧一档，或显式续期开工",
    "tighten-or-decompose": "拆出真子集子户口后再收紧",
    "split-proper-subset": "把子户口改成更短的目录 glob",
}


def finalize_ingest(manifest: Manifest, *, actor: str, reason: str) -> dict[str, Any]:
    policy = load_policy(manifest)
    knowledge_ids = [card.card_id for card in policy.cards if card.card_type == "knowledge" and card.references]
    synced = None
    if knowledge_ids:
        synced = sync_knowledge(manifest, policy, card_ids=knowledge_ids, actor=actor, reason=reason)
    build_index(manifest, policy, index_path(manifest))
    try:
        from .households import acknowledge_exploring

        acknowledge_exploring(manifest, policy, actor=actor, reason=reason)
    except AG2CError:
        pass
    event = append_event(
        manifest.ledger_path,
        "governance-ingested",
        {
            "actor": actor,
            "reason": reason,
            "knowledge": knowledge_ids,
            "floors": [card.card_id for card in policy.cards if card.card_type == "floor"],
            "boundaries": [card.card_id for card in policy.cards if card.card_type == "boundary"],
        },
    )
    pending_updates(manifest.project_root)
    return {
        "knowledge": knowledge_ids,
        "synced": None if synced is None else synced["cards"],
        "floors": [card.card_id for card in policy.cards if card.card_type == "floor"],
        "boundaries": [card.card_id for card in policy.cards if card.card_type == "boundary"],
        "relations": len(policy.relations),
        "ledger_event_digest": event["event_digest"],
    }


def ingest_project(start: Path, *, actor: str, reason: str) -> dict[str, Any]:
    actor = actor.strip()
    reason = reason.strip()
    if not actor:
        raise AG2CError("governance ingest requires --actor")
    if not reason:
        raise AG2CError("governance ingest requires --reason")
    root = repository_root(start)
    manifest = load_manifest(discover_manifest(root), project_root=root)
    raw = _read_json(manifest.policy_path)
    from .enrollment import _native_checkers, _tracked_roots

    project_roots = _tracked_roots(root)
    checkers = raw.get("checkers") or _native_checkers(root)
    checker_ids = [str(item["id"]) for item in checkers if isinstance(item, dict)]
    coverage = raw.get("coverage") if isinstance(raw.get("coverage"), dict) else {}
    generated = coverage.get("managed_by") == "ag2c" and coverage.get("level") == "baseline"
    composed = compose_baseline_governance(root, project_roots, checker_ids)
    if generated:
        raw["cards"] = composed["cards"]
        raw["relations"] = composed["relations"]
        raw["contracts"] = raw.get("contracts") or []
        raw["coverage"] = {
            "level": "baseline",
            "strategy": "conservative",
            "managed_by": "ag2c",
            "areas": project_roots,
        }
    else:
        existing = {str(card.get("id")) for card in raw.get("cards", []) if isinstance(card, dict)}
        owned_roots = _jurisdiction_include_roots(raw.get("cards") or [])
        for card in composed["cards"]:
            if card["id"] in existing or card["type"] not in {"knowledge", "boundary"}:
                continue
            if card.get("jurisdiction") and _include_roots_overlap(_card_include_roots(card), owned_roots):
                continue
            raw.setdefault("cards", []).append(card)
            existing.add(card["id"])
            owned_roots.update(_card_include_roots(card))
        known = {str(item.get("source")) + ":" + str(item.get("type")) + ":" + str(item.get("target")) for item in raw.get("relations", [])}
        for relation in composed["relations"]:
            key = f"{relation['source']}:{relation['type']}:{relation['target']}"
            if key not in known:
                raw.setdefault("relations", []).append(relation)
    _atomic_json(manifest.policy_path, raw)
    try:
        load_policy(manifest)
    except ConfigurationError as exc:
        raise AG2CError(f"ingested policy is invalid: {exc}") from exc
    result = finalize_ingest(manifest, actor=actor, reason=reason)
    result["generated"] = generated
    result["reason"] = reason
    result["actor"] = actor
    return result


def pending_updates(start: Path, changed_paths: list[str] | None = None) -> dict[str, Any]:
    root = repository_root(start)
    manifest = load_manifest(discover_manifest(root), project_root=root)
    policy = load_policy(manifest)
    from .enrollment import _tracked_roots

    items: list[dict[str, str]] = []
    owned: set[str] = set()
    for card in policy.cards:
        if card.card_type != "floor":
            continue
        for scope in card.scopes:
            for pattern in scope.includes:
                owned.add(pattern.replace("/**", "").rstrip("*").rstrip("/"))
    # 根文件认领口径（t58，t56 布局缓存 ini 的教训）：根条目是文件时，任意卡的
    # 精确 include（无 glob）或 references 收录即算有主——知识卡认领根文件是
    # 合法登记，不是"没登记"。根目录口径不变：只有 floor 能认领目录。
    claimed_files: set[str] = set()
    for card in policy.cards:
        for scope in card.scopes:
            for pattern in scope.includes:
                if not any(mark in pattern for mark in "*?["):
                    claimed_files.add(pattern)
        claimed_files.update(card.references)
    for name in _tracked_roots(root):
        if name in owned or any(name.startswith(prefix + "/") or prefix == name for prefix in owned if prefix):
            continue
        if not (root / name).is_dir() and name in claimed_files:
            continue
        items.append({"kind": "unowned-area", "path": name, "action": "add-or-expand-floor"})
    referenced = {ref.replace("\\", "/") for card in policy.cards for ref in card.references}
    for relative in _document_paths(root):
        if relative not in referenced:
            items.append({"kind": "new-document", "path": relative, "action": "add-knowledge"})
    for status in knowledge_status(manifest, policy):
        if status.get("jurisdiction") and status["status"] != "current":
            items.append({"kind": "census-review-required", "path": status["id"], "action": "review-directory-census"})
        elif status["status"] == "conflict":
            items.append({"kind": "assertion-conflict", "path": status["id"], "action": "review-then-sync-knowledge"})
        elif status["status"] == "stale":
            items.append({"kind": "stale-knowledge", "path": status["id"], "action": "sync-or-update-knowledge"})
    for relative in changed_paths or []:
        normalized = relative.replace("\\", "/").lstrip("./")
        if normalized.endswith(".md") and normalized not in referenced:
            items.append({"kind": "changed-document", "path": normalized, "action": "add-or-update-knowledge"})
        if any(part.lower() in BOUNDARY_HINTS for part in Path(normalized).parts):
            if not any(normalized.startswith(str(scope.includes[0]).replace("/**", "")) for card in policy.cards if card.card_type == "boundary" for scope in card.scopes if scope.includes):
                items.append({"kind": "new-interface", "path": normalized, "action": "add-boundary"})
    if not policy.contracts and not any(checker.stage in {"boundary", "scenario"} for checker in policy.checkers):
        items.append({"kind": "undeclared-product", "path": ".", "action": "declare-product-checks"})
    from .households import census_report, load_renewals

    try:
        report = census_report(manifest, policy)
        renewals = load_renewals(manifest)
    except AG2CError:
        report = None
        renewals = {}
    if report:
        for record in report.get("households") or []:
            if not record.get("jurisdiction"):
                continue
            card_id = str(record["id"])
            codes = {str(issue.get("code")) for issue in record.get("issues") or []}
            if record.get("identity") == "opaque" or "opaque-claimed" in codes:
                items.append({"kind": "opaque-household", "path": card_id, "action": "tighten-or-decompose"})
            if "child-not-proper-subset" in codes:
                items.append({"kind": "fake-child", "path": card_id, "action": "split-proper-subset"})
            if record.get("identity") == "exploring" and record.get("child_directories"):
                acknowledged = list((renewals.get(card_id) or {}).get("child_directories") or [])
                if acknowledged != list(record.get("child_directories") or []):
                    items.append({"kind": "tighten-or-renew", "path": card_id, "action": "tighten-or-renew-exploring"})
        exploring_ids = {str(item["id"]) for item in report.get("households") or [] if item.get("identity") == "exploring"}
        items = [
            item
            for item in items
            if not (item.get("kind") == "census-review-required" and item.get("path") in exploring_ids)
        ]
    unique: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        key = (item["kind"], item["path"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(
            {
                **item,
                "title": PENDING_TITLES.get(item["kind"], item["kind"]),
                "hint": PENDING_HINTS.get(item["action"], item["action"]),
            }
        )
    stored = {"updated_at": _now(), "items": unique}
    _atomic_json(manifest.state_dir / PENDING_FILENAME, stored)
    return stored


def settle_pending(start: Path, *, actor: str, reason: str) -> dict[str, Any]:
    actor = actor.strip()
    reason = reason.strip()
    if not actor or not reason:
        raise AG2CError("governance settle requires --actor and --reason")
    pending = pending_updates(start)
    items = list(pending.get("items") or [])
    actions: list[str] = []
    kinds = {str(item.get("kind")) for item in items}
    if kinds & {"unowned-area", "new-document", "changed-document", "new-interface"}:
        ingest_project(start, actor=actor, reason=reason)
        actions.append("ingest")
    stale_ids = [str(item["path"]) for item in items if item.get("kind") == "stale-knowledge"]
    if stale_ids:
        root = repository_root(start)
        manifest = load_manifest(discover_manifest(root), project_root=root)
        policy = load_policy(manifest)
        sync_knowledge(manifest, policy, card_ids=stale_ids, actor=actor, reason=reason)
        actions.append("sync")
    # Assertion conflicts and household identity debts stay pending; settle never
    # records a census as named or clears exploring/opaque/fake-child items.
    # 动态预算：结算时按最新普查自动重标（系统算，用户被告知）。
    # 重标失败不阻断结算，但必须可观测——写进结果的 budgets_error 字段。
    budgets_error = ""
    try:
        from .budgets import recalibrate_budgets

        root = repository_root(start)
        manifest = load_manifest(discover_manifest(root), project_root=root)
        budget_table = recalibrate_budgets(manifest, load_policy(manifest), actor=actor, reason=reason)
        if any(row.get("action") != "kept" for row in budget_table.get("rooms") or []):
            actions.append("budgets")
    except (AG2CError, OSError, ValueError, ConfigurationError) as exc:
        budgets_error = f"{type(exc).__name__}: {exc}"
    # t50 验证成本治理：结算时按账本耗时历史重标验证预算（同动态房间预算规约——
    # 失败不阻断结算，但必须可观测，写进结果的 verify_budgets_error 字段）。
    verify_budgets_error = ""
    try:
        from .verify_costs import recalibrate_verify_budgets

        root = repository_root(start)
        manifest = load_manifest(discover_manifest(root), project_root=root)
        verify_table = recalibrate_verify_budgets(manifest, load_policy(manifest), actor=actor, reason=reason)
        if any(row.get("action") != "kept" for row in verify_table.get("checkers") or []):
            actions.append("verify-budgets")
    except (AG2CError, OSError, ValueError, ConfigurationError) as exc:
        verify_budgets_error = f"{type(exc).__name__}: {exc}"
    remaining = pending_updates(start)
    event = append_event(
        load_manifest(discover_manifest(repository_root(start))).ledger_path,
        "governance-settled",
        {"actor": actor, "reason": reason, "actions": actions, "settled": len(items), "remaining": len(remaining.get("items") or [])},
    )
    return {
        "actor": actor,
        "reason": reason,
        "actions": actions,
        "settled": items,
        "pending": remaining.get("items") or [],
        "budgets_error": budgets_error,
        "verify_budgets_error": verify_budgets_error,
        "ledger_event_digest": event["event_digest"],
    }


def apply_change(
    start: Path,
    *,
    action: str,
    kind: str,
    card_id: str,
    reason: str,
    actor: str,
    card_type: str = "knowledge",
    title: str = "",
    summary: str = "",
    include: list[str] | None = None,
    provides: list[str] | None = None,
    conventions: str | None = None,
    budget_lines: int | None = None,
    budget_chars: int | None = None,
    budget_ast_nodes: int | None = None,
    optional: bool | None = None,
    maturity: str | None = None,
) -> dict[str, Any]:
    actor = actor.strip()
    reason = reason.strip()
    card_id = card_id.strip()
    if not actor or not reason or not card_id:
        raise AG2CError("governance apply requires --actor, --reason, and --id")
    if action not in {"add", "update", "remove"}:
        raise AG2CError("governance action must be add, update, or remove")
    if kind != "card":
        raise AG2CError("this release applies card changes; add a boundary or Knowledge card to record a protocol")
    root = repository_root(start)
    manifest = load_manifest(discover_manifest(root), project_root=root)
    raw = _read_json(manifest.policy_path)
    cards = [item for item in raw.get("cards", []) if isinstance(item, dict)]
    existing = {str(item.get("id")): item for item in cards}
    if existing.get(card_id, {}).get("jurisdiction") is not None:
        raise AG2CError("directory households must be updated through govern household; retain retired cards and census history")
    if action == "remove":
        if card_id not in existing:
            raise AG2CError(f"unknown card: {card_id}")
        if existing[card_id].get("type") == "constitution":
            raise AG2CError("refusing to remove the constitution card")
        if existing[card_id].get("type") == "floor" and sum(1 for item in cards if item.get("type") == "floor") <= 1:
            raise AG2CError("refusing to remove the last floor card")
        raw["cards"] = [item for item in cards if item.get("id") != card_id]
        raw["relations"] = [
            item
            for item in raw.get("relations", [])
            if isinstance(item, dict) and item.get("source") != card_id and item.get("target") != card_id
        ]
    else:
        includes = [normalize_artifact_path(item) for item in (include or existing.get(card_id, {}).get("scopes", [{}])[0].get("include") or [])]
        if action == "add" and card_id in existing:
            raise AG2CError(f"card already exists: {card_id}")
        if action == "update" and card_id not in existing:
            raise AG2CError(f"unknown card: {card_id}")
        if action == "add" and card_type not in {"knowledge", "boundary", "floor"}:
            raise AG2CError("new cards must be knowledge, boundary, or floor")
        current = dict(existing.get(card_id) or {})
        current["id"] = card_id
        current["type"] = card_type if action == "add" else current.get("type") or card_type
        current["title"] = title.strip() or current.get("title") or card_id
        current["summary"] = summary.strip() or current.get("summary") or reason
        if current.get("type") == "knowledge":
            stored_title = str(current.get("title") or "").strip()
            if len(stored_title) > KNOWLEDGE_TITLE_LIMIT:
                raise AG2CError(
                    f"knowledge card title is the 摘要 and must be at most {KNOWLEDGE_TITLE_LIMIT} characters; "
                    "Chinese is allowed, the English id is not the display name"
                )
        if not includes:
            raise AG2CError("card apply requires --include")
        current["scopes"] = [{"target": "app", "include": includes, "ownership": "primary" if current["type"] == "floor" else "reference"}]
        if current["type"] == "floor":
            checker_ids = [str(item["id"]) for item in raw.get("checkers", []) if isinstance(item, dict)]
            if not checker_ids:
                raise AG2CError("floor cards require an existing checker")
            current["checkers"] = current.get("checkers") or [checker_ids[0]]
        else:
            current.pop("checkers", None)
        if current["type"] == "knowledge":
            current["references"] = includes
        if provides is not None:
            if not isinstance(provides, list) or any(not isinstance(item, str) or not item.strip() for item in provides):
                raise AG2CError("provides must be a list of non-empty strings")
            current["provides"] = [item.strip() for item in provides]
        if conventions is not None:
            current["conventions"] = conventions.strip()
        if budget_lines is not None:
            current["budget_lines"] = max(0, int(budget_lines))
        if budget_chars is not None:
            current["budget_chars"] = max(0, int(budget_chars))
        if budget_ast_nodes is not None:
            current["budget_ast_nodes"] = max(0, int(budget_ast_nodes))
        if optional is not None:
            current["optional"] = bool(optional)
        if maturity is not None:
            current["maturity"] = maturity.strip()
        # 证据锚：写新卡或改 provides 时必须锚对——provides 的每个条目都要在
        # references 指向的 Python 文件里有真实顶层符号。存量卡不追改 provides 的
        # update 不校验（迁移期由 census warning 覆盖）。
        if current["type"] == "knowledge" and current.get("provides") and (action == "add" or provides is not None):
            from .anchors import anchor_violations

            unanchored = anchor_violations(root, list(current["provides"]), list(current.get("references") or includes))
            if unanchored:
                raise AG2CError(
                    "provides 锚定失败（证据锚）：以下条目在 references 指向的文件里找不到对应顶层符号：\n- "
                    + "\n- ".join(unanchored)
                    + "\nprovides 是可验证断言，不是散文：写出 references 文件里真实存在的函数/类/常量名，或先修正 references。"
                )
        if action == "add":
            cards.append(current)
            raw["cards"] = cards
            floor_id = _floor_for_path(cards, includes[0])
            if floor_id and current["type"] == "knowledge":
                raw.setdefault("relations", []).append({"source": card_id, "type": "explains", "target": floor_id})
        else:
            raw["cards"] = [current if item.get("id") == card_id else item for item in cards]
    _atomic_json(manifest.policy_path, raw)
    try:
        policy = load_policy(manifest)
    except ConfigurationError as exc:
        raise AG2CError(f"updated policy is invalid: {exc}") from exc
    build_index(manifest, policy, index_path(manifest))
    remaining = next((card for card in policy.cards if card.card_id == card_id), None)
    if remaining is not None and remaining.card_type == "knowledge" and remaining.references:
        sync_knowledge(manifest, policy, card_ids=[card_id], actor=actor, reason=reason)
    event = append_event(
        manifest.ledger_path,
        "governance-applied",
        {"action": action, "kind": kind, "id": card_id, "actor": actor, "reason": reason},
    )
    pending_updates(root)
    return {
        "action": action,
        "id": card_id,
        "actor": actor,
        "reason": reason,
        "ledger_event_digest": event["event_digest"],
    }


CHECKER_STAGES = ("static", "floor", "boundary", "scenario")


def update_checker(
    start: Path,
    *,
    checker_id: str,
    actor: str,
    reason: str,
    always: bool | None = None,
    parse: str | None = None,
    timeout: int | None = None,
    command: list[str] | None = None,
    stage: str | None = None,
    bind: list[str] | None = None,
    budget_seconds: float | None = None,
) -> dict[str, Any]:
    """Create or adjust a policy checker without hand-editing policy.json.

    Unknown id + --command creates the checker (default stage floor); a known
    id updates only the fields passed. Policy forbids orphaned checkers, so
    creating requires --bind <card> (repeatable); binding also works on an
    existing checker and unions into each card's checker list.
    """
    actor = actor.strip()
    reason = reason.strip()
    checker_id = checker_id.strip()
    if not actor or not reason or not checker_id:
        raise AG2CError("governance checker requires --actor, --reason, and --id")
    if always is None and parse is None and timeout is None and command is None and stage is None and not bind and budget_seconds is None:
        raise AG2CError("nothing to change; pass --always, --parse, --timeout, --command, --stage, --bind, or --budget-seconds")
    if parse is not None and parse not in {"unittest", "none", ""}:
        raise AG2CError(f"unsupported parse mode: {parse}")
    if command is not None and (not command or any(not isinstance(item, str) or not item for item in command)):
        raise AG2CError("checker command must be a nonempty JSON array of strings")
    if stage is not None and stage not in CHECKER_STAGES:
        raise AG2CError(f"unsupported checker stage: {stage}; expected one of {', '.join(CHECKER_STAGES)}")
    root = repository_root(start)
    manifest = load_manifest(discover_manifest(root), project_root=root)
    raw = _read_json(manifest.policy_path)
    checkers = [item for item in raw.get("checkers", []) if isinstance(item, dict)]
    target = next((item for item in checkers if str(item.get("id")) == checker_id), None)
    changes: dict[str, Any] = {}
    action = "update"
    if target is None:
        if command is None:
            raise AG2CError(f"unknown checker: {checker_id}; pass --command to create it")
        if not bind:
            raise AG2CError("a new checker must be bound to a card; pass --bind <card-id>")
        target = {
            "id": checker_id,
            "stage": stage or "floor",
            "target": "app",
            "cwd": ".",
            "command": list(command),
            "timeout": 600,
        }
        checkers.append(target)
        raw["checkers"] = checkers
        action = "create"
        changes["created"] = True
        changes["command"] = list(command)
        if stage is not None:
            changes["stage"] = stage
    elif command is not None:
        target["command"] = list(command)
        changes["command"] = list(command)
    if stage is not None and action == "update":
        target["stage"] = stage
        changes["stage"] = stage
    if always is not None:
        target["always"] = always
        changes["always"] = always
    if parse is not None:
        value = "" if parse in {"none", ""} else parse
        if value:
            target["parse"] = value
        else:
            target.pop("parse", None)
        changes["parse"] = value
    if timeout is not None:
        if timeout < 1:
            raise AG2CError("timeout must be positive")
        target["timeout"] = timeout
        changes["timeout"] = timeout
    if budget_seconds is not None:
        if budget_seconds < 0:
            raise AG2CError("budget_seconds must be non-negative")
        if budget_seconds > 0:
            target["budget_seconds"] = budget_seconds
        else:
            target.pop("budget_seconds", None)  # 0 = 清除显式预算，回到动态仓
        changes["budget_seconds"] = budget_seconds
    if bind:
        cards = [item for item in raw.get("cards", []) if isinstance(item, dict)]
        known = {str(item.get("id")) for item in cards}
        unknown = sorted({str(card_id).strip() for card_id in bind} - known)
        if unknown:
            raise AG2CError("cannot bind checker; unknown cards: " + ", ".join(unknown))
        bound: list[str] = []
        for card in cards:
            if str(card.get("id")) not in {str(card_id).strip() for card_id in bind}:
                continue
            owned = [str(item) for item in card.get("checkers", []) if str(item)]
            if checker_id not in owned:
                owned.append(checker_id)
                card["checkers"] = owned
                bound.append(str(card.get("id")))
        if bound:
            changes["bound"] = bound
    before = manifest.policy_path.read_text(encoding="utf-8")
    _atomic_json(manifest.policy_path, raw)
    try:
        policy = load_policy(manifest)
    except ConfigurationError as exc:
        manifest.policy_path.write_text(before, encoding="utf-8")
        raise AG2CError(f"updated policy is invalid (rolled back): {exc}") from exc
    build_index(manifest, policy, index_path(manifest))
    event = append_event(
        manifest.ledger_path,
        "governance-applied",
        {"action": action, "kind": "checker", "id": checker_id, "changes": changes, "actor": actor, "reason": reason},
    )
    pending_updates(root)
    return {
        "action": action,
        "kind": "checker",
        "id": checker_id,
        "changes": changes,
        "actor": actor,
        "reason": reason,
        "ledger_event_digest": event["event_digest"],
    }


def configure_regulator(
    start: Path,
    *,
    actor: str,
    reason: str,
    enabled: bool | None = None,
    endpoint: str | None = None,
    model: str | None = None,
    api_key_env: str | None = None,
    strict: bool | None = None,
    timeout: int | None = None,
    worker_model: str | None = None,
    allow_same_family: bool | None = None,
) -> dict[str, Any]:
    """Configure the AI regulator (agent-review) without hand-editing policy.json.

    Only the fields passed are changed; disabling keeps endpoint/model so a
    parked regulator can be re-enabled without retyping. Enabling without
    endpoint/model fails policy validation and rolls back.

    9.10 安达信条款：启用状态下监管模型与 worker_model 同族时拒绝配置，
    除非 allow_same_family=True 显式豁免（豁免进账本并返回大字警告）。
    """
    actor = actor.strip()
    reason = reason.strip()
    if not actor or not reason:
        raise AG2CError("governance regulator requires --actor and --reason")
    if (
        enabled is None
        and endpoint is None
        and model is None
        and api_key_env is None
        and strict is None
        and timeout is None
        and worker_model is None
        and allow_same_family is None
    ):
        raise AG2CError(
            "nothing to change; pass --enable, --endpoint, --model, --api-key-env, --strict, --timeout, --worker-model, or --allow-same-family"
        )
    root = repository_root(start)
    manifest = load_manifest(discover_manifest(root), project_root=root)
    raw = _read_json(manifest.policy_path)
    current = raw.get("regulator")
    target = dict(current) if isinstance(current, dict) else {}
    changes: dict[str, Any] = {}
    if enabled is not None:
        target["enabled"] = enabled
        changes["enabled"] = enabled
    if endpoint is not None:
        target["endpoint"] = endpoint.strip()
        changes["endpoint"] = target["endpoint"]
    if model is not None:
        target["model"] = model.strip()
        changes["model"] = target["model"]
    if api_key_env is not None:
        target["api_key_env"] = api_key_env.strip()
        changes["api_key_env"] = target["api_key_env"]
    if strict is not None:
        target["strict"] = strict
        changes["strict"] = strict
    if timeout is not None:
        if timeout < 1:
            raise AG2CError("timeout must be positive")
        target["timeout"] = timeout
        changes["timeout"] = timeout
    if worker_model is not None:
        target["worker_model"] = worker_model.strip()
        changes["worker_model"] = target["worker_model"]
    if allow_same_family is not None:
        target["allow_same_family"] = allow_same_family
        changes["allow_same_family"] = allow_same_family
    # 9.10 安达信条款：对合并后的目标状态做同族检测（启用才判定）。
    from .review import model_family, same_family

    family_warning = ""
    if target.get("enabled") and same_family(str(target.get("model", "")), str(target.get("worker_model", ""))):
        regulator_family = model_family(str(target.get("model", "")))
        if not target.get("allow_same_family"):
            raise AG2CError(
                "监管模型与 worker 同族（安达信条款），配置被拒绝："
                f"regulator={target.get('model')} worker={target.get('worker_model')} 同属 {regulator_family}。"
                "监管的钱不能由被监管者出——换一个厂商的监管模型，"
                "或显式 --allow-same-family 申报豁免（会进账本）。"
            )
        family_warning = (
            f"⚠⚠⚠ 安达信条款豁免：监管与 worker 同属 {regulator_family} 家族，异构名存实亡。"
            "此豁免已写入 policy 与账本，复盘时须说明理由。⚠⚠⚠"
        )
    raw["regulator"] = target
    before = manifest.policy_path.read_text(encoding="utf-8")
    _atomic_json(manifest.policy_path, raw)
    try:
        policy = load_policy(manifest)
    except ConfigurationError as exc:
        manifest.policy_path.write_text(before, encoding="utf-8")
        raise AG2CError(f"updated policy is invalid (rolled back): {exc}") from exc
    build_index(manifest, policy, index_path(manifest))
    event = append_event(
        manifest.ledger_path,
        "governance-applied",
        {
            "action": "update",
            "kind": "regulator",
            "id": "regulator",
            "changes": changes,
            "actor": actor,
            "reason": reason,
            **({"same_family_exemption": family_warning} if family_warning else {}),
        },
    )
    pending_updates(root)
    return {
        "action": "update",
        "kind": "regulator",
        "changes": changes,
        "actor": actor,
        "reason": reason,
        "ledger_event_digest": event["event_digest"],
        **({"warning": family_warning} if family_warning else {}),
    }


_PROXY_FLAGS = frozenset({"auto_settle", "auto_census", "auto_warning"})


def configure_proxy(
    start: Path,
    *,
    actor: str,
    reason: str,
    auto_settle: bool | None = None,
    auto_census: bool | None = None,
    auto_warning: bool | None = None,
    grant: bool = False,
    rule_id: str = "",
    rule_flag: str = "",
) -> dict[str, Any]:
    """Set L0 proxy flags or grant an L1 named rule. Does not auto-merge."""
    actor, reason = actor.strip(), reason.strip()
    if not actor or not reason:
        raise AG2CError("governance proxy requires --actor and --reason")
    if auto_settle is None and auto_census is None and auto_warning is None and not grant:
        raise AG2CError("nothing to change; pass --auto-settle, --auto-census, --auto-warning, or --grant")
    root = repository_root(start)
    manifest = load_manifest(discover_manifest(root), project_root=root)
    raw = _read_json(manifest.policy_path)
    current = raw.get("proxy")
    target = dict(current) if isinstance(current, dict) else {}
    changes: dict[str, Any] = {}
    for key, value in (("auto_settle", auto_settle), ("auto_census", auto_census), ("auto_warning", auto_warning)):
        if value is not None:
            target[key] = value
            changes[key] = value
    grant_blob: dict[str, str] | None = None
    if grant:
        rid, rflag = rule_id.strip(), rule_flag.strip()
        if not rid or rflag not in _PROXY_FLAGS:
            raise AG2CError("grant requires --rule-id and --flag auto_settle|auto_census|auto_warning")
        rules = [item for item in (target.get("rules") or []) if isinstance(item, dict)]
        if any(str(item.get("id") or "") == rid for item in rules):
            raise AG2CError(f"proxy rule already granted: {rid}")
        grant_blob = {"id": rid, "flag": rflag}
        rules.append(grant_blob)
        target["rules"] = rules
        target[rflag] = True
        changes["grant"] = grant_blob
        changes[rflag] = True
    raw["proxy"] = target
    before = manifest.policy_path.read_text(encoding="utf-8")
    _atomic_json(manifest.policy_path, raw)
    try:
        policy = load_policy(manifest)
    except ConfigurationError as exc:
        manifest.policy_path.write_text(before, encoding="utf-8")
        raise AG2CError(f"updated policy is invalid (rolled back): {exc}") from exc
    build_index(manifest, policy, index_path(manifest))
    event = append_event(
        manifest.ledger_path,
        "proxy-grant" if grant else "governance-applied",
        {"action": "update", "kind": "proxy", "id": "proxy", "changes": changes, "actor": actor, "reason": reason, **({"grant": grant_blob} if grant_blob else {})},
    )
    pending_updates(root)
    result = {"action": "update", "kind": "proxy", "changes": changes, "actor": actor, "reason": reason, "ledger_event_digest": event["event_digest"]}
    if grant_blob:
        result["grant"] = grant_blob
    return result


def record_pending_from_task(canonical: Path, changed_paths: list[str]) -> dict[str, Any]:
    return pending_updates(canonical, changed_paths)

from .govern_ingest import _document_paths, compose_baseline_governance, configure_trunk, retrieve_guidance, stored_pending
