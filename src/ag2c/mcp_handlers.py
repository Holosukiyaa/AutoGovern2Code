"""Extracted by flatten-split."""
from __future__ import annotations
import sys
from pathlib import Path
from typing import Any, Callable, Mapping
from . import __version__
from .errors import AG2CError
from .harnesses import PACKAGED_SKILLS
from .mcp_server import MCP_INSTRUCTIONS, PROTOCOL_VERSIONS, SERVER_NAME, _actor, _args, _call_rehome, _call_verify, _cwd, _cwd_prop, _optional_int, _optional_string_list, _read_resource, _read_skill, _skill_resources, _string_list, _text_result, _tool, install_mcp_clients, mcp_health, refresh_engine_from_disk

def tool_defs() -> list[dict[str, Any]]:
    return [
        _tool("ag2c_guard_status", "Check whether this Git repo is AG2C-managed. Call before any write.", {"cwd": _cwd_prop()}),
        _tool(
            "ag2c_task_start",
            "Start a governed task worktree. Requires a 结果门 portrait: simulate the finished state BEFORE coding and lock it. Returns guidance.lineage (knowledge-card 谱系 index). Write only in worktree.path.",
            {
                "goal": {"type": "string", "description": "What to implement or fix."},
                "portrait": {
                    "type": "string",
                    "description": "结果门: the checkable finished-state portrait, written from outside the implementation — Done looks like (2-4 sentences an outsider could accept/reject) / Surfaces (each observable surface with example + empty/error/success) / Out of result (what will NOT exist) / Inferences (each guessed detail marked INFERRED). Not steps, not files-to-edit, not architecture. Linted at start: too-thin (<60 chars), no-verification-layer (declare how each done-state gets checked: 机器验证/实机/用户确认/test/output...), and vague-phrase (正常工作/没问题/优化/完善/合理/works as expected...) are refused.",
                },
                "paths": {"type": "array", "items": {"type": "string"}, "description": "app:relative/path entries."},
                "contracts": {"type": "array", "items": {"type": "string"}},
                "all": {"type": "boolean"},
                "touches_verification": {
                    "type": "boolean",
                    "description": "巴林条款申报：本任务将同时修改产品代码与验证它的测试。申报后 verify 放行但记 intervention 并提升监管审查级别；不申报的同改会被 verify 拦截。",
                },
                "coordinates": {
                    "type": "object",
                    "description": "AGF 七维坐标申报（可选）：effect/contract/meaning/quality/decider/grain/failure，封闭枚举（见 agf/src/agf/models.py）；未申报维度从触及卡片的 jurisdiction 保守推导，多卡冲突取更严档。只申报记录，不执法。",
                },
                "cwd": _cwd_prop(),
            },
            ["goal", "portrait"],
        ),
        _tool("ag2c_task_verify", "Verify the current task worktree from its actual diff.", {"cwd": _cwd_prop()}),
        _tool(
            "ag2c_task_declare",
            "巴林条款中途申报：本任务必须同改产品代码与验证它的测试。写入任务记录（含时间戳与理由）后 verify 放行，但记 intervention front-back-declared 且监管提示词标注自我阅卷。",
            {"reason": {"type": "string", "description": "为什么必须同改（必填，进证据链）"}, "cwd": _cwd_prop()},
            ["reason"],
        ),
        _tool(
            "ag2c_task_amend_portrait",
            "画像修订：任务中途按市长指名的纠偏更换已锁画像。lint 后替换并记 intervention portrait-amended（actor/reason/新旧 digest 落账本）；verify 时监管看到修订史，裁决市长纠偏 vs 自利漂移。",
            {
                "portrait": {"type": "string", "description": "新画像全文（结果门格式，会被 lint）"},
                "actor": {"type": "string", "description": "谁批准这次修订（必填，进证据链）"},
                "reason": {"type": "string", "description": "市长指名的纠偏内容（必填，进证据链）"},
                "cwd": _cwd_prop(),
            },
            ["portrait", "actor", "reason"],
        ),
        _tool(
            "ag2c_rehome",
            "Move a file card into another room (or a subdirectory of it) through the governed loop: the card scope updates, a task worktree does git mv + repo-wide Python import rewrite, census + verify gate the merge, and any failure rolls everything back. Python files only; never __init__.py. Runs in the background like ag2c_task_verify: answers within 45s or returns a job id — call again with that job id to poll.",
            {
                "id": {"type": "string", "description": "File card id, e.g. knowledge.backend-main."},
                "room": {"type": "string", "description": "Target room card id, e.g. knowledge.backend."},
                "subdir": {"type": "string", "description": "Optional subdirectory inside the room, e.g. routers."},
                "job": {"type": "string", "description": "Poll a running rehome job by id."},
                "reason": {"type": "string"},
                "cwd": _cwd_prop(),
            },
        ),
        _tool(
            "ag2c_task_finish",
            "Finish a verified task from the canonical checkout. message names the product change; proof 自证 backs every side-effecting claim with this-session tool output.",
            {
                "task": {"type": "string"},
                "message": {"type": "string"},
                "proof": {
                    "type": "string",
                    "description": "自证: for each claim with side effects (files changed, behavior changed), quote the this-session tool output that proves it (command + output fragment). Read-only observations need no proof. 'Tests passed' without the output is not proof.",
                },
                "sessions": {
                    "type": "integer",
                    "description": "Optional INFERRED session count for cost-report. Omit to skip.",
                },
                "estimated_tokens": {
                    "type": "object",
                    "description": "Optional INFERRED {model, input, output} for cost-report. Omit to skip.",
                },
                "cwd": _cwd_prop(),
            },
            ["task", "message", "proof"],
        ),
        _tool("ag2c_task_list", "List governed tasks and worktree lifecycle.", {"cwd": _cwd_prop()}),
        _tool(
            "ag2c_task_orient",
            "Orientation packet for a governed task: phase, lifecycle checklist, next action with prefilled args, blockers. Call first in a new session; without a task id it returns the open-task queue.",
            {"task": {"type": "string"}, "cwd": _cwd_prop()},
        ),
        _tool("ag2c_task_refresh", "Rebase an open task onto current canonical HEAD.", {"task": {"type": "string"}, "cwd": _cwd_prop()}, ["task"]),
        _tool(
            "ag2c_task_abandon",
            "Abandon an obsolete open task worktree.",
            {"task": {"type": "string"}, "reason": {"type": "string"}, "cwd": _cwd_prop()},
            ["task"],
        ),
        _tool(
            "ag2c_retrieve",
            "Retrieve lineage and households for paths without starting a task.",
            {
                "goal": {"type": "string"},
                "paths": {"type": "array", "items": {"type": "string"}},
                "cwd": _cwd_prop(),
            },
        ),
        _tool(
            "ag2c_census",
            "Observe directory households, or record a review after inspecting a room. Never bulk-record unread rooms.",
            {
                "record": {"type": "boolean"},
                "all": {"type": "boolean", "description": "With record: review every known household and floor. Required when no card ids are given."},
                "card": {"type": "array", "items": {"type": "string"}},
                "reason": {"type": "string"},
                "actor": {"type": "string"},
                "verbose": {
                    "type": "boolean",
                    "description": "Return the full census report (record: under census; observe: as the payload). Default is a summary (household_count / freshness / stale).",
                },
                "cwd": _cwd_prop(),
            },
        ),
        _tool(
            "ag2c_span",
            "Set a directory room coverage tag: 未打标 / 整夹一张 / 一文件一张. Agent writes; user supervises.",
            {
                "id": {"type": "string"},
                "tag": {"type": "string"},
                "reason": {"type": "string"},
                "actor": {"type": "string"},
                "cwd": _cwd_prop(),
            },
            ["id", "tag", "reason"],
        ),
        _tool(
            "ag2c_household",
            "Register or update a directory household. Proper-subset glob only. Exclude carved children.",
            {
                "id": {"type": "string"},
                "title": {"type": "string"},
                "summary": {"type": "string"},
                "include": {"type": "array", "items": {"type": "string"}},
                "exclude": {"type": "array", "items": {"type": "string"}},
                "floor": {"type": "array", "items": {"type": "string"}},
                "capability": {"type": "string"},
                "implementation": {"type": "string"},
                "span": {"type": "string"},
                "meaning": {"type": "string"},
                "entrypoint": {"type": "array", "items": {"type": "string"}, "description": "Entry files. Omit to keep existing; pass to replace."},
                "checker": {"type": "array", "items": {"type": "string"}, "description": "Checker ids. Omit to keep existing; pass to replace."},
                "command": {"type": "array", "items": {"type": "string"}, "description": "Scenario checker command (argv). Declares a product check for this household."},
                "provides": {"type": "array", "items": {"type": "string"}, "description": "Reusable capabilities this room offers (货架). Omit to keep existing; pass to replace."},
                "conventions": {"type": "string", "description": "写法约定: how code in this room is written (state, errors, UI). Omit to keep existing."},
                "budget_lines": {"type": "integer", "description": "Explicit line budget for this room (人工预算, overrides the dynamic store). Omit to keep existing; 0 clears."},
                "reason": {"type": "string"},
                "actor": {"type": "string"},
                "cwd": _cwd_prop(),
            },
            ["id", "title", "summary", "include", "floor", "capability", "implementation", "reason"],
        ),
        _tool(
            "ag2c_tighten",
            "Tighten a directory household strategy (grain/meaning/contract/decider), or renew an exploring household.",
            {
                "id": {"type": "string"},
                "grain": {"type": "string", "enum": ["", "subtree", "directory", "module"]},
                "meaning": {"type": "string", "enum": ["", "none", "named"]},
                "contract": {"type": "string", "enum": ["", "none", "partial", "machine"]},
                "decider": {"type": "string", "enum": ["", "none", "machine", "confirm"]},
                "renew": {"type": "boolean", "description": "Renew an exploring household instead of tightening it."},
                "reason": {"type": "string"},
                "actor": {"type": "string"},
                "cwd": _cwd_prop(),
            },
            ["id", "reason"],
        ),
        _tool(
            "ag2c_apply",
            "Add or update a named document or per-file knowledge card. Not for directory households.",
            {
                "action": {"type": "string", "description": "add, update, or remove"},
                "id": {"type": "string"},
                "title": {"type": "string"},
                "summary": {"type": "string"},
                "include": {"type": "array", "items": {"type": "string"}},
                "provides": {"type": "array", "items": {"type": "string"}, "description": "Reusable capabilities this module offers (货架). Omit to keep existing; pass to replace."},
                "conventions": {"type": "string", "description": "写法约定: how code in this module is written. Omit to keep existing."},
                "budget_lines": {"type": "integer", "description": "Soft budget: max lines of code. Omit to keep existing. Setting it also derives chars/AST ceilings (anti-density-gaming)."},
                "budget_chars": {"type": "integer", "description": "Soft budget: max characters. 0 = derive from budget_lines. Omit to keep existing."},
                "budget_ast_nodes": {"type": "integer", "description": "Soft budget: max AST nodes (Python files). 0 = derive from budget_lines. Omit to keep existing."},
                "reason": {"type": "string"},
                "actor": {"type": "string"},
                "cwd": _cwd_prop(),
            },
            ["action", "id", "reason"],
        ),
        _tool(
            "ag2c_settle",
            "Settle pending document/interface discovery after a merge. Does not name households.",
            {"reason": {"type": "string"}, "actor": {"type": "string"}, "cwd": _cwd_prop()},
            ["reason"],
        ),
        _tool("ag2c_evidence", "Plain-language evidence for a finished task.", {"task": {"type": "string"}, "cwd": _cwd_prop()}),
        _tool("ag2c_doctor_repair", "Restore Git guard and MCP config if activation is broken.", {"cwd": _cwd_prop()}),
        _tool(
            "ag2c_skill",
            "Return a packaged Skill markdown by name. Prefer initialize instructions; use this for the full text.",
            {"name": {"type": "string", "description": "One of: " + ", ".join(PACKAGED_SKILLS)}},
            ["name"],
        ),
        _tool(
            "ag2c_cost_report",
            "Read-only development-cost dashboard: efficiency / economy (MTok) / effectiveness. No prices, no gating.",
            {"cwd": _cwd_prop()},
        ),
        _tool(
            "ag2c_mcp_health",
            "Detect whether this AG2C MCP server can start, and whether the Git guard is on when cwd is a project.",
            {
                "handshake": {
                    "type": "boolean",
                    "description": "Spawn the stdio server and initialize. Default true.",
                },
                "cwd": _cwd_prop(),
            },
        ),
    ]

def _call_guard(args: dict[str, Any]) -> Any:
    from .enrollment import activation_status

    return activation_status(_cwd(args))

def _call_start(args: dict[str, Any]) -> Any:
    from .tasks import start_task

    portrait = str(args.get("portrait") or "").strip()
    if not portrait:
        raise AG2CError(
            "ag2c_task_start requires a 结果门 portrait: simulate the checkable finished state "
            "(Done looks like / Surfaces / Out of result / Inferences) and lock it before coding."
        )
    paths = _string_list(args, "paths") or _string_list(args, "path")
    coordinates = args.get("coordinates")
    if coordinates is not None and not isinstance(coordinates, Mapping):
        raise AG2CError("coordinates must be an object of dimension=value")
    return start_task(
        _cwd(args, required=True),
        goal=str(args.get("goal") or ""),
        path_specs=paths,
        contract_specs=_string_list(args, "contracts"),
        all_mode=bool(args.get("all")),
        portrait=portrait,
        touches_verification=bool(args.get("touches_verification")),
        coordinates=dict(coordinates) if coordinates else None,
    )

def _call_task_declare(args: dict[str, Any]) -> Any:
    from .tasks import declare_front_back

    return declare_front_back(_cwd(args, required=True), reason=str(args.get("reason") or ""))

def _call_task_amend_portrait(args: dict[str, Any]) -> Any:
    from .tasks import amend_portrait

    return amend_portrait(
        _cwd(args, required=True),
        portrait=str(args.get("portrait") or ""),
        actor=str(args.get("actor") or ""),
        reason=str(args.get("reason") or ""),
    )

def _call_finish(args: dict[str, Any]) -> Any:
    from .tasks import finish_task

    proof = str(args.get("proof") or "").strip()
    if not proof:
        raise AG2CError(
            "ag2c_task_finish requires 自证 proof: for every side-effecting claim, quote the "
            "this-session tool output that proves it. Read-only observations need no proof."
        )
    estimated = args.get("estimated_tokens")
    if estimated is not None and not isinstance(estimated, dict):
        raise AG2CError("estimated_tokens must be an object {model, input, output}")
    sessions = args.get("sessions")
    if sessions is not None and type(sessions) is not int:
        raise AG2CError("sessions must be a non-negative integer")
    return finish_task(
        _cwd(args, required=True),
        str(args.get("task") or ""),
        message=str(args.get("message") or ""),
        proof=proof,
        sessions=sessions,
        estimated_tokens=estimated,
    )

def _call_list(args: dict[str, Any]) -> Any:
    from .task_orient import list_tasks

    return list_tasks(_cwd(args))

def _call_orient(args: dict[str, Any]) -> Any:
    from .task_orient import orient_task

    task = str(args.get("task") or "").strip()
    return orient_task(_cwd(args), task or None)

def _call_refresh(args: dict[str, Any]) -> Any:
    from .task_orient import refresh_task

    return refresh_task(_cwd(args, required=True), str(args.get("task") or ""))

def _call_abandon(args: dict[str, Any]) -> Any:
    from .task_orient import abandon_task

    return abandon_task(_cwd(args, required=True), str(args.get("task") or ""), reason=str(args.get("reason") or "mcp abandon"))

def _call_retrieve(args: dict[str, Any]) -> Any:
    from .govern import retrieve_guidance

    paths = _string_list(args, "paths") or _string_list(args, "path")
    return retrieve_guidance(
        _cwd(args),
        path_specs=paths,
        contract_specs=_string_list(args, "contracts"),
        goal=str(args.get("goal") or ""),
        all_mode=bool(args.get("all")),
    )

def _census_record_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    """MCP record payload: room count, freshness histogram, stale ids. Not the full tree."""
    households = list(report.get("households") or [])
    freshness = dict(((report.get("counts") or {}).get("freshness") or {}))
    stale = [str(item.get("id")) for item in households if item.get("freshness") == "stale"]
    return {
        "household_count": len(households),
        "freshness": freshness,
        "stale": stale,
    }

def _call_census(args: dict[str, Any]) -> Any:
    from .config import discover_manifest, load_manifest, load_policy
    from .gitops import repository_root
    from .households import census_report
    from .household_commands import review_census

    root = _cwd(args, required=bool(args.get("record")))
    if args.get("record"):
        cards = _string_list(args, "card") or _string_list(args, "cards")
        result = review_census(
            root,
            card_ids=cards,
            all_cards=bool(args.get("all")) and not cards,
            actor=_actor(args),
            reason=str(args.get("reason") or "").strip() or "mcp census record",
        )
        warning = _canonical_census_warning(root)
        if warning:
            result["warning"] = warning
        if not args.get("verbose"):
            result["census"] = _census_record_summary(result.get("census") or {})
        return result
    manifest = load_manifest(discover_manifest(repository_root(root)), project_root=root)
    report = census_report(manifest, load_policy(manifest))
    if args.get("verbose"):
        return report
    return _census_record_summary(report)

def _canonical_census_warning(root: Path) -> str | None:
    """cwd 脚枪提示：在 canonical 检出上录普查、且有开放任务时提醒。

    finish 的新鲜度门禁读的是 worktree 的普查记录；在 canonical 上录的记录
    对进行中的任务不算数。警告不阻塞（canonical 普查本身合法，如发版后全量）。
    """
    try:
        from .enrollment import activation_status
        from .tasks import TERMINAL_TASK_STATES
        from .task_orient import list_tasks

        status = activation_status(root)
        canonical = Path(status["canonical_root"]).resolve()
        if root.resolve() != canonical:
            return None
        open_tasks = [t for t in list_tasks(root) if t.get("state") not in TERMINAL_TASK_STATES]
        if not open_tasks:
            return None
        lines = [
            "census recorded on the CANONICAL checkout while tasks are open; "
            "finish reads the task worktree's records, so record again with cwd=<worktree> for:",
        ]
        for task in open_tasks:
            worktree = (task.get("worktree") or {}).get("path") or "<no worktree>"
            lines.append(f"- {task['id']} [{task.get('state')}] worktree: {worktree}")
        return "\n".join(lines)
    except Exception:
        return None

def _call_span(args: dict[str, Any]) -> Any:
    from .household_commands import set_household_span

    return set_household_span(
        _cwd(args, required=True),
        card_id=str(args.get("id") or ""),
        span=str(args.get("tag") or args.get("span") or ""),
        actor=_actor(args),
        reason=str(args.get("reason") or ""),
    )

def _call_household(args: dict[str, Any]) -> Any:
    from .household_commands import register_household

    return register_household(
        _cwd(args, required=True),
        card_id=str(args.get("id") or ""),
        title=str(args.get("title") or ""),
        summary=str(args.get("summary") or ""),
        includes=_string_list(args, "include"),
        excludes=_string_list(args, "exclude"),
        floors=_string_list(args, "floor"),
        capability=str(args.get("capability") or ""),
        implementation=str(args.get("implementation") or ""),
        status=str(args.get("status") or "current"),
        grain=str(args.get("grain") or ""),
        meaning=str(args.get("meaning") or ""),
        contract=str(args.get("contract") or ""),
        decider=str(args.get("decider") or ""),
        span=str(args.get("span") or ""),
        entrypoints=_optional_string_list(args, "entrypoint"),
        checkers=_optional_string_list(args, "checker"),
        command=_optional_string_list(args, "command"),
        provides=_optional_string_list(args, "provides"),
        conventions=str(args["conventions"]) if args.get("conventions") is not None else None,
        budget_lines=int(args["budget_lines"]) if args.get("budget_lines") is not None else None,
        actor=_actor(args),
        reason=str(args.get("reason") or ""),
    )

def _call_tighten(args: dict[str, Any]) -> Any:
    from .household_commands import renew_exploring, tighten_household

    if args.get("renew"):
        return renew_exploring(_cwd(args, required=True), card_id=str(args.get("id") or ""), actor=_actor(args), reason=str(args.get("reason") or ""))
    return tighten_household(
        _cwd(args, required=True),
        card_id=str(args.get("id") or ""),
        grain=str(args.get("grain") or ""),
        meaning=str(args.get("meaning") or ""),
        contract=str(args.get("contract") or ""),
        decider=str(args.get("decider") or ""),
        actor=_actor(args),
        reason=str(args.get("reason") or ""),
    )

def _call_apply(args: dict[str, Any]) -> Any:
    from .govern import apply_change

    return apply_change(
        _cwd(args, required=True),
        action=str(args.get("action") or ""),
        kind="card",
        card_id=str(args.get("id") or ""),
        reason=str(args.get("reason") or ""),
        actor=_actor(args),
        card_type=str(args.get("type") or "knowledge"),
        title=str(args.get("title") or ""),
        summary=str(args.get("summary") or ""),
        include=_string_list(args, "include"),
        provides=_optional_string_list(args, "provides"),
        conventions=str(args["conventions"]) if args.get("conventions") is not None else None,
        budget_lines=_optional_int(args, "budget_lines"),
        budget_chars=_optional_int(args, "budget_chars"),
        budget_ast_nodes=_optional_int(args, "budget_ast_nodes"),
    )

def _call_settle(args: dict[str, Any]) -> Any:
    from .govern import settle_pending

    return settle_pending(_cwd(args, required=True), actor=_actor(args), reason=str(args.get("reason") or ""))

def _call_evidence(args: dict[str, Any]) -> Any:
    from .tasks import evidence

    task = str(args.get("task") or "").strip() or None
    return evidence(_cwd(args), task)

def _call_doctor(args: dict[str, Any]) -> Any:
    from .enrollment import repair_project

    repair_project(_cwd(args, required=True))
    return install_mcp_clients()

def _call_skill(args: dict[str, Any]) -> Any:
    name = str(args.get("name") or "").strip()
    return {"name": name, "text": _read_skill(f"ag2c://skill/{name}")}

def _call_cost_report(args: dict[str, Any]) -> Any:
    from .config import discover_manifest, load_manifest
    from .token import cost_report

    root = _cwd(args)
    manifest = load_manifest(discover_manifest(root), project_root=root)
    return cost_report(manifest)

def _call_health(args: dict[str, Any]) -> Any:
    handshake = args.get("handshake")
    cwd = str(args.get("cwd") or args.get("root") or "").strip()
    return mcp_health(
        handshake=True if handshake is None else bool(handshake),
        cwd=cwd or None,
    )

HANDLERS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "ag2c_guard_status": _call_guard,
    "ag2c_task_start": _call_start,
    "ag2c_task_declare": _call_task_declare,
    "ag2c_task_amend_portrait": _call_task_amend_portrait,
    "ag2c_task_verify": _call_verify,
    "ag2c_rehome": _call_rehome,
    "ag2c_task_finish": _call_finish,
    "ag2c_task_list": _call_list,
    "ag2c_task_orient": _call_orient,
    "ag2c_task_refresh": _call_refresh,
    "ag2c_task_abandon": _call_abandon,
    "ag2c_retrieve": _call_retrieve,
    "ag2c_census": _call_census,
    "ag2c_span": _call_span,
    "ag2c_household": _call_household,
    "ag2c_tighten": _call_tighten,
    "ag2c_apply": _call_apply,
    "ag2c_settle": _call_settle,
    "ag2c_evidence": _call_evidence,
    "ag2c_doctor_repair": _call_doctor,
    "ag2c_skill": _call_skill,
    "ag2c_cost_report": _call_cost_report,
    "ag2c_mcp_health": _call_health,
}

def handle_mcp_request(message: Mapping[str, Any]) -> dict[str, Any] | None:
    """Handle one JSON-RPC request. Notifications return None."""
    method = str(message.get("method") or "")
    req_id = message.get("id")
    params = message.get("params") if isinstance(message.get("params"), Mapping) else {}
    if req_id is None:
        return None
    try:
        if method == "initialize":
            requested = str(params.get("protocolVersion") or PROTOCOL_VERSIONS[0])
            version = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": version,
                    "capabilities": {"tools": {}, "resources": {}},
                    "serverInfo": {"name": SERVER_NAME, "version": __version__},
                    "instructions": MCP_INSTRUCTIONS.strip(),
                },
            }
        if method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tool_defs()}}
        if method == "tools/call":
            name = str(params.get("name") or "")
            if name != "ag2c_mcp_health":
                refresh_engine_from_disk()
            handlers = sys.modules[__name__].HANDLERS
            handler = handlers.get(name)
            if handler is None:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": _text_result(f"unknown tool: {name}", is_error=True),
                }
            result = handler(_args(params.get("arguments")))
            return {"jsonrpc": "2.0", "id": req_id, "result": _text_result(result)}
        if method == "resources/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"resources": _skill_resources()}}
        if method == "resources/read":
            uri = str(params.get("uri") or "")
            text, mime = _read_resource(uri)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"contents": [{"uri": uri, "mimeType": mime, "text": text}]},
            }
        if method == "prompts/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"prompts": []}}
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}
    except AG2CError as exc:
        if method == "tools/call":
            return {"jsonrpc": "2.0", "id": req_id, "result": _text_result(str(exc), is_error=True)}
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": str(exc)}}
    except Exception as exc:  # noqa: BLE001 — MCP must not crash the stdio loop
        if method == "tools/call":
            return {"jsonrpc": "2.0", "id": req_id, "result": _text_result(f"{type(exc).__name__}: {exc}", is_error=True)}
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32603, "message": f"{type(exc).__name__}: {exc}"}}
