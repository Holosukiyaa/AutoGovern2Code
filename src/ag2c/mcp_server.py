"""Local stdio MCP server. Skill docs ship as initialize instructions and resources."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Mapping

from . import __version__
from .errors import AG2CError
from .harnesses import PACKAGED_SKILLS, skill_source
from .util import hidden_process_kwargs

PROTOCOL_VERSIONS = (
    "2025-03-26",
    "2025-06-18",
    "2024-11-05",
    "2025-11-25",
    "2026-06-18",
)
SERVER_NAME = "ag2c"
MCP_CONFIG_KEY = "ag2c"
PYTHON_PLACEHOLDER = "<python>"
SRC_PLACEHOLDER = "<ag2c-src>"
CONNECT_RESOURCE_URI = "ag2c://connect"

MCP_INSTRUCTIONS = """This workspace is governed by AutoGovern2Code (AG2C) when `ag2c_guard_status` reports managed.

You already have the AG2C workflow through this MCP connection (instructions, resources, tools). Do not ask the user to paste a copy-prompt, install Skill folders, or configure Git. Do not git commit on the canonical checkout.

Route:
- New session with work possibly in flight: ag2c_task_orient first. It returns the phase, checklist, and the exact next tool call (or the open-task queue when several tasks are open).
- File-changing work: ag2c_guard_status → ag2c_task_start (read guidance.lineage as the knowledge-card index) → write only in worktree.path → ag2c_census / ag2c_span / ag2c_household / ag2c_tighten / ag2c_apply as needed → ag2c_task_verify → ag2c_task_finish → ag2c_settle if pending → ag2c_evidence.
- Tree investigation and coverage tags (未打标 / 整夹一张 / 一文件一张): ag2c_census then ag2c_span. The user supervises tags; they do not click tray buttons.
- Write 设计思路 from tags: ag2c_apply for per-file cards, ag2c_household for 整夹一张 rooms. Read the files first.
- Named README/interface cards: ag2c_apply. Never edit Policy JSON by hand.
- Full liquidation (全量清算: wipe stale cards, re-census, re-author, audit, cleanup queue): resource ag2c://skill/ag2c-full-liquidation. Run it ONLY when the user explicitly asks — never offer or start it proactively.

Delivery is the Git hook, not this MCP. Connecting MCP does not replace pre-commit. AG2C uses its own Git binary on the project's existing `.git` and history.

Hard rules learned in production:
- Governance writes (ag2c_census record, ag2c_span, ag2c_household, ag2c_apply, ag2c_settle) require a reason; pass actor to name yourself.
- After editing files, verify blocks on census-stale: record the census first (ag2c_census with record=true, all=true).
- A knowledge-card title is the 摘要: 20 characters max, Chinese allowed; the English id is not the display name.
- ag2c_task_verify runs the full suite and can exceed the MCP timeout; on timeout rerun `ag2c task verify` via CLI inside the worktree — it counts the same.
- Checkers marked always:true run on every verify regardless of slice. Checkers with parse:unittest get a zero-regression gate: failures listed in the store baseline stay green, any NEW failure blocks verify, and fixed failures shrink the baseline automatically. Record the initial debt once with `ag2c govern test-baseline --actor ... --reason ...`; tune checkers with `ag2c govern checker --id ... --always on|off --parse unittest|none`.
- ag2c_task_finish runs from the canonical checkout, never from the worktree.

Fail closed: dirty canonical blocks start; writes outside the worktree block verify; leftover deletion needs retire then a dedicated task. Full Skill text is in resources ag2c://skill/<name>. The generic connect prompt is ag2c://connect.
"""


def mcp_stdio_command() -> list[str]:
    """Console interpreter plus `mcp`. Never pythonw: stdio needs a console."""
    exe = Path(sys.executable).resolve()
    if exe.stem.lower() == "pythonw":
        sibling = exe.with_name("python.exe" if exe.suffix.lower() == ".exe" else "python")
        if sibling.is_file():
            exe = sibling
    if getattr(sys, "frozen", False):
        return [str(exe), "mcp"]
    return [str(exe), "-m", "ag2c", "mcp"]


def mcp_launch_spec() -> dict[str, Any]:
    command = mcp_stdio_command()
    src = str(Path(__file__).resolve().parents[1])
    return {"command": command[0], "args": command[1:], "env": {"PYTHONPATH": src}}


def mcp_placeholder_spec() -> dict[str, Any]:
    """Launch snippet with placeholders only. Never interpolate user paths or vendors."""
    return {
        "command": PYTHON_PLACEHOLDER,
        "args": ["-m", "ag2c", "mcp"],
        "env": {"PYTHONPATH": SRC_PLACEHOLDER},
    }


def mcp_connect_prompt() -> str:
    """Generic MCP connect instructions. No vendor names, no absolute paths."""
    spec = mcp_placeholder_spec()
    json_block = json.dumps(
        {
            "mcpServers": {
                MCP_CONFIG_KEY: {
                    "command": spec["command"],
                    "args": spec["args"],
                    "env": spec["env"],
                }
            }
        },
        ensure_ascii=False,
        indent=2,
    )
    toml_block = (
        f"[mcp_servers.{MCP_CONFIG_KEY}]\n"
        f"command = {json.dumps(spec['command'])}\n"
        f"args = [{', '.join(json.dumps(item) for item in spec['args'])}]\n"
        f"env = {{ PYTHONPATH = {json.dumps(SRC_PLACEHOLDER)} }}\n"
        "enabled = true\n"
    )
    return "\n".join(
        [
            "将 AG2C 作为本地 stdio MCP 接到你的编程 agent。不要绑定某一家产品。",
            "Connect AG2C as a local stdio MCP server in your coding agent. Do not lock this to one vendor.",
            "",
            "Server key: ag2c",
            "Transport: stdio",
            f"command: {PYTHON_PLACEHOLDER}",
            'args: ["-m", "ag2c", "mcp"]',
            f"env.PYTHONPATH: {SRC_PLACEHOLDER}",
            "",
            "Placeholders:",
            f"  {PYTHON_PLACEHOLDER}     console Python (python, not pythonw)",
            f"  {SRC_PLACEHOLDER}   the `src` directory of this AG2C install",
            "",
            "JSON:",
            json_block,
            "",
            "TOML:",
            toml_block.rstrip(),
            "",
            "接上后新开一轮对话。Skill 全文和施工工具都在这个 MCP 里：不要再装 Skill 目录，也不要再贴复制提示词。",
            "交付门禁仍是 Git hook；连上 MCP 不会替代它。AG2C 用自带 Git 操作已有仓库，不改写历史。",
        ]
    )


def _text_result(payload: Any, *, is_error: bool = False) -> dict[str, Any]:
    if isinstance(payload, (dict, list)):
        text = json.dumps(payload, ensure_ascii=False, indent=2)
    else:
        text = str(payload)
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _args(raw: Any) -> dict[str, Any]:
    return dict(raw) if isinstance(raw, Mapping) else {}


def _cwd(args: Mapping[str, Any]) -> Path:
    raw = str(args.get("cwd") or args.get("root") or "").strip()
    start = Path(raw) if raw else Path.cwd()
    try:
        from .gitops import repository_root

        return repository_root(start)
    except AG2CError:
        return start.resolve()


def _actor(args: Mapping[str, Any]) -> str:
    return str(args.get("actor") or "mcp").strip() or "mcp"


def _string_list(args: Mapping[str, Any], key: str) -> list[str]:
    value = args.get(key)
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _optional_string_list(args: Mapping[str, Any], key: str) -> list[str] | None:
    """None when the caller omitted the key, so the engine preserves existing values."""
    if key not in args or args.get(key) is None:
        return None
    return _string_list(args, key)


def _skill_resources() -> list[dict[str, str]]:
    rows = [
        {
            "uri": CONNECT_RESOURCE_URI,
            "name": "connect",
            "title": "MCP connect prompt",
            "mimeType": "text/plain",
            "description": "Generic stdio MCP connect instructions with placeholders.",
        }
    ]
    for name in PACKAGED_SKILLS:
        rows.append(
            {
                "uri": f"ag2c://skill/{name}",
                "name": name,
                "title": name,
                "mimeType": "text/markdown",
                "description": f"Packaged AG2C Skill {name}",
            }
        )
    return rows


def _read_skill(uri: str) -> str:
    name = uri.removeprefix("ag2c://skill/").strip("/")
    if name not in PACKAGED_SKILLS:
        raise AG2CError(f"unknown AG2C Skill: {name}")
    return (skill_source(name) / "SKILL.md").read_text(encoding="utf-8")


def _read_resource(uri: str) -> tuple[str, str]:
    key = uri.strip()
    if key.rstrip("/") == CONNECT_RESOURCE_URI:
        return mcp_connect_prompt(), "text/plain"
    return _read_skill(key), "text/markdown"


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        schema["required"] = required
    return {"name": name, "description": description, "inputSchema": schema}


def _cwd_prop() -> dict[str, Any]:
    return {"type": "string", "description": "Git project root. Defaults to the MCP process cwd."}


def tool_defs() -> list[dict[str, Any]]:
    return [
        _tool("ag2c_guard_status", "Check whether this Git repo is AG2C-managed. Call before any write.", {"cwd": _cwd_prop()}),
        _tool(
            "ag2c_task_start",
            "Start a governed task worktree. Returns guidance.lineage (knowledge-card 谱系 index). Write only in worktree.path.",
            {
                "goal": {"type": "string", "description": "What to implement or fix."},
                "paths": {"type": "array", "items": {"type": "string"}, "description": "app:relative/path entries."},
                "contracts": {"type": "array", "items": {"type": "string"}},
                "all": {"type": "boolean"},
                "cwd": _cwd_prop(),
            },
            ["goal"],
        ),
        _tool("ag2c_task_verify", "Verify the current task worktree from its actual diff.", {"cwd": _cwd_prop()}),
        _tool(
            "ag2c_task_finish",
            "Finish a verified task from the canonical checkout. --message names the product change.",
            {
                "task": {"type": "string"},
                "message": {"type": "string"},
                "cwd": _cwd_prop(),
            },
            ["task", "message"],
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

    paths = _string_list(args, "paths") or _string_list(args, "path")
    return start_task(
        _cwd(args),
        goal=str(args.get("goal") or ""),
        path_specs=paths,
        contract_specs=_string_list(args, "contracts"),
        all_mode=bool(args.get("all")),
    )


def _call_verify(args: dict[str, Any]) -> Any:
    from .tasks import verify_task

    return verify_task(_cwd(args))


def _call_finish(args: dict[str, Any]) -> Any:
    from .tasks import finish_task

    return finish_task(_cwd(args), str(args.get("task") or ""), message=str(args.get("message") or ""))


def _call_list(args: dict[str, Any]) -> Any:
    from .tasks import list_tasks

    return list_tasks(_cwd(args))


def _call_orient(args: dict[str, Any]) -> Any:
    from .tasks import orient_task

    task = str(args.get("task") or "").strip()
    return orient_task(_cwd(args), task or None)


def _call_refresh(args: dict[str, Any]) -> Any:
    from .tasks import refresh_task

    return refresh_task(_cwd(args), str(args.get("task") or ""))


def _call_abandon(args: dict[str, Any]) -> Any:
    from .tasks import abandon_task

    return abandon_task(_cwd(args), str(args.get("task") or ""), reason=str(args.get("reason") or "mcp abandon"))


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


def _call_census(args: dict[str, Any]) -> Any:
    from .config import discover_manifest, load_manifest, load_policy
    from .gitops import repository_root
    from .households import census_report
    from .household_commands import review_census

    root = _cwd(args)
    if args.get("record"):
        cards = _string_list(args, "card") or _string_list(args, "cards")
        return review_census(
            root,
            card_ids=cards,
            all_cards=bool(args.get("all")) and not cards,
            actor=_actor(args),
            reason=str(args.get("reason") or "").strip() or "mcp census record",
        )
    manifest = load_manifest(discover_manifest(repository_root(root)), project_root=root)
    return census_report(manifest, load_policy(manifest))


def _call_span(args: dict[str, Any]) -> Any:
    from .household_commands import set_household_span

    return set_household_span(
        _cwd(args),
        card_id=str(args.get("id") or ""),
        span=str(args.get("tag") or args.get("span") or ""),
        actor=_actor(args),
        reason=str(args.get("reason") or ""),
    )


def _call_household(args: dict[str, Any]) -> Any:
    from .household_commands import register_household

    return register_household(
        _cwd(args),
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
        actor=_actor(args),
        reason=str(args.get("reason") or ""),
    )


def _call_tighten(args: dict[str, Any]) -> Any:
    from .household_commands import renew_exploring, tighten_household

    if args.get("renew"):
        return renew_exploring(_cwd(args), card_id=str(args.get("id") or ""), actor=_actor(args), reason=str(args.get("reason") or ""))
    return tighten_household(
        _cwd(args),
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
        _cwd(args),
        action=str(args.get("action") or ""),
        kind="card",
        card_id=str(args.get("id") or ""),
        reason=str(args.get("reason") or ""),
        actor=_actor(args),
        card_type=str(args.get("type") or "knowledge"),
        title=str(args.get("title") or ""),
        summary=str(args.get("summary") or ""),
        include=_string_list(args, "include"),
    )


def _call_settle(args: dict[str, Any]) -> Any:
    from .govern import settle_pending

    return settle_pending(_cwd(args), actor=_actor(args), reason=str(args.get("reason") or ""))


def _call_evidence(args: dict[str, Any]) -> Any:
    from .tasks import evidence

    task = str(args.get("task") or "").strip() or None
    return evidence(_cwd(args), task)


def _call_doctor(args: dict[str, Any]) -> Any:
    from .enrollment import repair_project

    repair_project(_cwd(args))
    return install_mcp_clients()


def _call_skill(args: dict[str, Any]) -> Any:
    name = str(args.get("name") or "").strip()
    return {"name": name, "text": _read_skill(f"ag2c://skill/{name}")}


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
    "ag2c_task_verify": _call_verify,
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
            handler = HANDLERS.get(name)
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


def _decode_line(line: str) -> dict[str, Any] | None:
    text = line.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _reconfigure_utf8(stream: Any) -> None:
    """Force a stdio stream to UTF-8 so a locale console cannot corrupt JSON-RPC.

    MCP clients speak UTF-8 JSON. On a locale console (for example GBK on
    Chinese Windows) the inherited stdin otherwise decodes tool arguments
    with the locale codec, producing mojibake or surrogate escapes that later
    crash strict UTF-8 file writes.
    """
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:
        return
    try:
        reconfigure(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        pass


def serve_mcp_stdio(stdin=None, stdout=None) -> int:
    """Newline-delimited JSON-RPC MCP loop. Logs go to stderr only."""
    if stdin is None:
        _reconfigure_utf8(sys.stdin)
    if stdout is None:
        _reconfigure_utf8(sys.stdout)
    reader = stdin or sys.stdin
    writer = stdout or sys.stdout
    while True:
        try:
            line = reader.readline()
        except (OSError, UnicodeDecodeError):
            return 1
        if line == "":
            return 0
        message = _decode_line(line)
        if message is None:
            continue
        reply = handle_mcp_request(message)
        if reply is None:
            continue
        writer.write(json.dumps(reply, ensure_ascii=False, separators=(",", ":")) + "\n")
        writer.flush()


def mcp_config_snippet(*, placeholders: bool = False) -> dict[str, Any]:
    spec = mcp_placeholder_spec() if placeholders else mcp_launch_spec()
    return {
        "mcpServers": {
            MCP_CONFIG_KEY: {
                "command": spec["command"],
                "args": spec["args"],
                "env": spec.get("env") or {},
            }
        }
    }


def mcp_toml_block(*, placeholders: bool = False) -> str:
    spec = mcp_placeholder_spec() if placeholders else mcp_launch_spec()
    args = ", ".join(json.dumps(item) for item in spec["args"])
    env = spec.get("env") or {}
    env_inline = ", ".join(f"{key} = {json.dumps(value)}" for key, value in env.items())
    env_line = f"env = {{ {env_inline} }}\n" if env_inline else ""
    return (
        f"[mcp_servers.{MCP_CONFIG_KEY}]\n"
        f"command = {json.dumps(spec['command'])}\n"
        f"args = [{args}]\n"
        f"{env_line}"
        "enabled = true\n"
    )


def _upsert_toml_table(path: Path, header: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    pattern = re.compile(rf"^\[{re.escape(header)}\]\s*\n(?:(?!^\[).*\n)*", re.MULTILINE)
    block = f"[{header}]\n{body.rstrip()}\n"
    if pattern.search(existing):
        text = pattern.sub(block + "\n", existing, count=1)
    else:
        text = existing.rstrip() + ("\n\n" if existing.strip() else "") + block
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


def _upsert_json_server(path: Path, key: str = "mcpServers") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            loaded = {}
        if isinstance(loaded, dict):
            data = loaded
    spec = mcp_launch_spec()
    servers = data.get(key)
    if not isinstance(servers, dict):
        servers = {}
    servers[MCP_CONFIG_KEY] = {"command": spec["command"], "args": spec["args"], "env": spec.get("env") or {}}
    data[key] = servers
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def default_mcp_targets(home: Path | None = None) -> list[tuple[str, Path, str]]:
    root = home or Path.home()
    appdata = root / "AppData" / "Roaming" if home is not None else Path(os.environ.get("APPDATA") or (root / "AppData" / "Roaming"))
    return [
        ("grok", root / ".grok" / "config.toml", "toml"),
        ("cursor", root / ".cursor" / "mcp.json", "json"),
        ("claude", root / ".claude.json", "json"),
        ("claude-desktop", appdata / "Claude" / "claude_desktop_config.json", "json"),
        ("codex", root / ".codex" / "config.toml", "toml"),
    ]


def install_mcp_clients(*, home: Path | None = None, create_missing: bool = True) -> list[dict[str, str]]:
    """Write this AG2C's stdio server into known agent MCP configs. Idempotent."""
    installed: list[dict[str, str]] = []
    for harness, path, kind in default_mcp_targets(home):
        if not create_missing and not path.exists() and not path.parent.is_dir():
            continue
        if harness == "claude-desktop" and not path.parent.is_dir():
            continue
        if kind == "toml":
            spec = mcp_launch_spec()
            args = ", ".join(json.dumps(item) for item in spec["args"])
            env = spec.get("env") or {}
            env_inline = ", ".join(f"{key} = {json.dumps(value)}" for key, value in env.items())
            env_line = f"env = {{ {env_inline} }}\n" if env_inline else ""
            body = f"command = {json.dumps(spec['command'])}\nargs = [{args}]\n{env_line}enabled = true\n"
            _upsert_toml_table(path, f"mcp_servers.{MCP_CONFIG_KEY}", body)
        else:
            _upsert_json_server(path)
        installed.append({"harness": harness, "path": str(path), "kind": kind})
    return installed


def mcp_client_probe(*, home: Path | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for harness, path, kind in default_mcp_targets(home):
        exists = path.is_file()
        configured = False
        if exists:
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                text = ""
            configured = MCP_CONFIG_KEY in text
        rows.append(
            {
                "harness": harness,
                "exists": exists,
                "configured": configured,
                "kind": kind,
            }
        )
    return rows


def probe_mcp_handshake(*, timeout: float = 8.0) -> dict[str, Any]:
    spec = mcp_launch_spec()
    env = os.environ.copy()
    env.update(spec.get("env") or {})
    message = (
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSIONS[0],
                    "capabilities": {},
                    "clientInfo": {"name": "ag2c-health", "version": __version__},
                },
            }
        )
        + "\n"
    )
    try:
        completed = subprocess.run(
            [spec["command"], *spec["args"]],
            input=message,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
            **hidden_process_kwargs(),
        )
    except FileNotFoundError as exc:
        return {"ok": False, "error": f"python missing: {exc}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "MCP handshake timed out"}
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    line = next((item for item in (completed.stdout or "").splitlines() if item.strip()), "")
    if not line:
        err = (completed.stderr or "").strip() or f"exit {completed.returncode}"
        return {"ok": False, "error": err[:500], "returncode": completed.returncode}
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return {"ok": False, "error": "MCP did not return JSON", "raw": line[:300]}
    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        err = ""
        if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
            err = str(payload["error"].get("message") or "")
        return {"ok": False, "error": err or "initialize failed", "raw": line[:300]}
    capabilities = result.get("capabilities") if isinstance(result.get("capabilities"), dict) else {}
    return {
        "ok": True,
        "protocol": result.get("protocolVersion"),
        "server": result.get("serverInfo"),
        "has_instructions": bool(str(result.get("instructions") or "").strip()),
        "capabilities": capabilities,
    }


def _guard_probe(cwd: str | Path | None = None, *, managed: bool | None = None) -> dict[str, Any] | None:
    if managed is not None:
        return {"managed": bool(managed), "issues": [] if managed else ["Git hook is off"]}
    if cwd is None or not str(cwd).strip():
        return None
    try:
        from .enrollment import activation_status

        status = activation_status(Path(str(cwd)))
    except AG2CError as exc:
        return {"managed": False, "issues": [str(exc)]}
    return {"managed": bool(status.get("managed")), "issues": list(status.get("issues") or [])}


def mcp_health(
    *,
    handshake: bool = True,
    home: Path | None = None,
    timeout: float = 8.0,
    cwd: str | Path | None = None,
    managed: bool | None = None,
) -> dict[str, Any]:
    spec = mcp_launch_spec()
    command = Path(str(spec["command"]))
    src = Path(str((spec.get("env") or {}).get("PYTHONPATH") or ""))
    python_ok = command.is_file()
    src_ok = src.is_dir() and (src / "ag2c").is_dir()
    clients = mcp_client_probe(home=home)
    configured = sum(1 for item in clients if item.get("configured"))
    handshake_result: dict[str, Any] | None = None
    if handshake and python_ok and src_ok:
        handshake_result = probe_mcp_handshake(timeout=timeout)
    handshake_ok = handshake_result is None or bool(handshake_result.get("ok"))
    guard = _guard_probe(cwd, managed=managed)
    guard_ok = True if guard is None else bool(guard.get("managed"))
    ok = bool(python_ok and src_ok and handshake_ok and guard_ok)
    status = "ok" if ok else "broken"
    label = "MCP 正常" if ok else "MCP 异常"
    error = ""
    if handshake_result and not handshake_result.get("ok"):
        error = str(handshake_result.get("error") or "")
    elif not python_ok:
        error = "console Python is missing"
    elif not src_ok:
        error = "AG2C src is missing"
    elif not guard_ok:
        issues = (guard or {}).get("issues") or []
        error = str(issues[0] if issues else "Git hook is off")
    return {
        "ok": ok,
        "status": status,
        "label": label,
        "error": error,
        "python_ok": python_ok,
        "src_ok": src_ok,
        "configured": configured,
        "skills_internalized": True,
        "skill_count": len(PACKAGED_SKILLS),
        "tool_count": len(tool_defs()),
        "handshake": handshake_result,
        "guard": guard,
        "clients": [{"harness": item["harness"], "configured": item["configured"]} for item in clients],
    }
