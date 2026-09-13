from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .checks import run_checks
from .config import discover_manifest, load_manifest, load_policy
from .errors import AG2CError
from .gitops import repository_root
from .index import build_index, findings, index_path, summary, verify_freshness
from .ledger import ledger_summary, verify_ledger
from .knowledge import knowledge_status, sync_knowledge
from .render import render_slice_markdown
from .harnesses import SUPPORTED_HARNESSES
from .slicer import compile_slice


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _configure_stdio() -> None:
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except (AttributeError, OSError, ValueError):
            pass
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


def _write_output(content: str, output: Path | None) -> None:
    if output is None:
        print(content)
        return
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content.rstrip() + "\n", encoding="utf-8")
    print(f"Wrote {output}")


def _loaded(args: argparse.Namespace):
    manifest_path = discover_manifest(explicit=args.manifest)
    project_root = None
    if args.manifest is None:
        try:
            project_root = repository_root(Path.cwd())
        except AG2CError:
            pass
    manifest = load_manifest(manifest_path, project_root=project_root)
    return manifest, load_policy(manifest)


def _slice_from_args(args: argparse.Namespace, manifest, policy):
    return compile_slice(
        manifest,
        policy,
        path_specs=list(args.paths or []),
        contract_specs=list(args.contracts or []),
        goal=args.goal or "",
        all_mode=bool(args.all),
    )


def _add_slice_arguments(parser: argparse.ArgumentParser, *, goal_required: bool = False) -> None:
    parser.add_argument("--path", dest="paths", action="append", default=[], help="target-id:relative/path")
    parser.add_argument("--contract", dest="contracts", action="append", default=[], help="target-id:contract-id@version")
    parser.add_argument(
        "--goal",
        default=None if goal_required else "",
        required=goal_required,
        help="advisory task description; never selects ownership by itself",
    )
    parser.add_argument("--all", action="store_true", help="select all policy areas and checkers")


def _add_harness_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--harness",
        dest="harnesses",
        action="append",
        choices=SUPPORTED_HARNESSES,
        help="install for one AI harness; repeat to select several (default: all)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ag2c",
        description="AutoGovern2Code: zero-touch governance for AI coding changes",
    )
    parser.add_argument("--version", action="version", version=f"AutoGovern2Code {__version__}")
    parser.add_argument("--manifest", type=Path, help="path to an AG2C manifest")
    subparsers = parser.add_subparsers(dest="command", required=True)

    setup = subparsers.add_parser("setup", help="install AG2C and optionally enroll, migrate, or upgrade one project")
    setup.add_argument("--project", type=Path)
    setup.add_argument("--project-id")
    setup.add_argument("--skill-destination", type=Path)
    _add_harness_arguments(setup)

    enroll = subparsers.add_parser("enroll", help="add a Git project to AutoGovern2Code")
    enroll.add_argument("path", type=Path, nargs="?", default=Path.cwd())
    enroll.add_argument("--project-id")
    _add_harness_arguments(enroll)

    activate = subparsers.add_parser("activate", help="restore the local Skill and Git guard after cloning")
    activate.add_argument("path", type=Path, nargs="?", default=Path.cwd())
    _add_harness_arguments(activate)

    upgrade = subparsers.add_parser("upgrade", help="upgrade tracked AG2C files and restore local activation")
    upgrade.add_argument("path", type=Path, nargs="?", default=Path.cwd())
    upgrade.add_argument("--skill-destination", type=Path)
    _add_harness_arguments(upgrade)

    migrate = subparsers.add_parser("migrate", help="migrate a clean legacy DEG enrollment to AG2C")
    migrate.add_argument("path", type=Path, nargs="?", default=Path.cwd())
    migrate.add_argument("--skill-destination", type=Path)
    _add_harness_arguments(migrate)

    skill = subparsers.add_parser("skill", help="print the Skill prompt and versions, or install/remove the packaged Skill")
    skill_commands = skill.add_subparsers(dest="skill_command", required=True)
    skill_prompt = skill_commands.add_parser("prompt")
    skill_prompt.add_argument("--project", type=Path, default=Path.cwd())
    skill_commands.add_parser("version", help="print packaged Skill versions and digests")
    skill_install = skill_commands.add_parser("install")
    skill_install.add_argument(
        "--destination",
        type=Path,
        help="custom skills directory; defaults to all supported harness locations",
    )
    _add_harness_arguments(skill_install)
    skill_uninstall = skill_commands.add_parser("uninstall")
    skill_uninstall.add_argument(
        "--destination",
        type=Path,
        help="custom skills directory; defaults to all supported harness locations",
    )
    _add_harness_arguments(skill_uninstall)

    mcp = subparsers.add_parser("mcp", help="stdio MCP server: internalized Skill workflow, live tools, health check")
    mcp_commands = mcp.add_subparsers(dest="mcp_command")
    mcp_commands.add_parser("serve", help="run the stdio MCP server (default)")
    mcp_commands.add_parser("install", help="write this AG2C into local agent MCP configs")
    mcp_commands.add_parser("config", help="print the generic MCP launch snippet (placeholders)")
    mcp_commands.add_parser("prompt", help="print the generic MCP connect prompt (placeholders)")
    mcp_commands.add_parser("health", help="detect whether the local AG2C MCP server works")

    project = subparsers.add_parser("project", help="manage externally governed projects")
    project_commands = project.add_subparsers(dest="project_command", required=True)
    project_list = project_commands.add_parser("list")
    project_list.add_argument("--format", choices=("text", "json"), default="text")
    project_add = project_commands.add_parser("add")
    project_add.add_argument("path", type=Path)
    project_status = project_commands.add_parser("status")
    project_status.add_argument("path", type=Path, nargs="?", default=Path.cwd())
    project_remove = project_commands.add_parser("remove")
    project_remove.add_argument("path", type=Path)
    project_remove.add_argument("--remove-data", action="store_true")
    project_uninstall = project_commands.add_parser("uninstall")
    project_uninstall.add_argument("path", type=Path)

    desktop = subparsers.add_parser("desktop", help="internal desktop management service")
    desktop_commands = desktop.add_subparsers(dest="desktop_command", required=True)
    desktop_serve = desktop_commands.add_parser("serve")
    desktop_serve.add_argument("--port", type=int, default=18992)
    desktop_serve.add_argument("--token", required=True)

    guard = subparsers.add_parser("guard", help="internal activation and Git enforcement")
    guard_commands = guard.add_subparsers(dest="guard_command", required=True)
    guard_commands.add_parser("status")
    guard_commands.add_parser("pre-commit")

    task = subparsers.add_parser("task", help="internal lifecycle used by the AG2C Skill")
    task_commands = task.add_subparsers(dest="task_command", required=True)
    task_start = task_commands.add_parser("start")
    _add_slice_arguments(task_start, goal_required=True)
    task_start.add_argument(
        "--portrait",
        required=True,
        help="结果门: the checkable finished-state portrait (Done looks like / Surfaces / Out of result / Inferences), locked before work begins",
    )
    task_start.add_argument("--task-id")
    task_start.add_argument("--worktree-root", type=Path)
    task_start.add_argument(
        "--touches-verification",
        action="store_true",
        help="申报：本任务将同时修改产品代码与验证它的测试（巴林条款），verify 放行但记 intervention 并提升监管审查级别",
    )
    task_start.add_argument(
        "--coordinate",
        action="append",
        default=[],
        metavar="DIM=VALUE",
        help="AGF 七维坐标申报（可重复）：effect/contract/meaning/quality/decider/grain/failure，封闭枚举；未申报维度从触及卡片的 jurisdiction 保守推导",
    )
    task_commands.add_parser("verify")
    task_declare = task_commands.add_parser(
        "declare", help="中途申报：默认前后台同改（巴林条款）；--full-scan 全量验收；--trust-base 可信基说明书"
    )
    task_declare.add_argument("--reason", required=True)
    task_declare.add_argument("--full-scan", action="store_true", help="申报全量验收：governance 变化触发全量时需先申报（申请预算语义），申报落账本")
    task_declare.add_argument("--trust-base", action="store_true", help="5.1 可信基变更说明书：改 GOVERNANCE_CODE_PATHS 时 verify 前必报")
    task_declare.add_argument("--why", default="")
    task_declare.add_argument("--risk", default="")
    task_declare.add_argument("--rollback", default="")
    task_declare.add_argument("--verify-how", dest="verify_how", default="")
    task_approve = task_commands.add_parser("approve", help="人工审批位：--trust-base 点头后 finish 放行")
    task_approve.add_argument("--trust-base", action="store_true")
    task_approve.add_argument("--actor", required=True)
    task_approve.add_argument("--reason", required=True)
    task_amend = task_commands.add_parser(
        "amend-portrait",
        help="画像修订：市长指名纠偏时更换已锁画像；lint 后替换并记 intervention（actor/reason/新旧 digest 落账本），verify 时监管可见修订史",
    )
    task_amend.add_argument("--portrait", default="", help="新画像全文（与 --portrait-file 二选一）")
    task_amend.add_argument("--portrait-file", type=Path, default=None, help="从文件读取新画像全文（UTF-8）")
    task_amend.add_argument("--actor", required=True, help="谁批准这次修订（进证据链）")
    task_amend.add_argument("--reason", required=True, help="市长指名的纠偏内容（进证据链）")
    task_list = task_commands.add_parser("list")
    task_list.add_argument("--format", choices=("text", "json"), default="text")
    task_orient = task_commands.add_parser("orient")
    task_orient.add_argument("--task")
    task_refresh = task_commands.add_parser("refresh")
    task_refresh.add_argument("--task", required=True)
    task_abandon = task_commands.add_parser("abandon")
    task_abandon.add_argument("--task", required=True)
    task_abandon.add_argument("--reason", default="")
    task_finish = task_commands.add_parser("finish")
    task_finish.add_argument("--task", required=True)
    task_finish.add_argument(
        "--message",
        required=True,
        help="what this task implemented or fixed; becomes the commit subject and the stored delivery record",
    )
    task_finish.add_argument(
        "--proof",
        required=True,
        help="自证: for each side-effecting claim, quote this-session tool output that proves it; read-only observations need no proof",
    )
    task_finish.add_argument("--sessions", type=int, default=None, help="optional INFERRED session count for cost-report")
    task_finish.add_argument(
        "--estimated-tokens",
        default="",
        help='optional INFERRED JSON {model,input,output} for cost-report',
    )
    task_show = task_commands.add_parser("show")
    task_show.add_argument("--task", required=True)

    evidence = subparsers.add_parser("evidence", help="show read-only proof of AG2C management")
    evidence.add_argument("--task")
    evidence.add_argument("--format", choices=("text", "json"), default="text")

    coverage = subparsers.add_parser("coverage", help="show the current conservative governance coverage")
    coverage.add_argument("--format", choices=("text", "json"), default="text")

    ci = subparsers.add_parser("ci", help="verify local AG2C evidence and optionally rerun trusted checks")
    ci_commands = ci.add_subparsers(dest="ci_command", required=True)
    ci_verify = ci_commands.add_parser("verify")
    ci_verify.add_argument("--commit", default="HEAD")
    ci_verify.add_argument("--rerun", action="store_true")
    ci_verify.add_argument("--format", choices=("text", "json"), default="text")

    index = subparsers.add_parser("index", help="build and inspect the repository index")
    index_commands = index.add_subparsers(dest="index_command", required=True)
    index_commands.add_parser("build")
    index_commands.add_parser("verify")
    index_commands.add_parser("summary")
    index_commands.add_parser("findings")

    slice_parser = subparsers.add_parser("slice", help="compile an entry slice")
    _add_slice_arguments(slice_parser)
    slice_parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    slice_parser.add_argument("--output", type=Path)

    check = subparsers.add_parser("check", help="run the checker plan selected by an entry slice")
    _add_slice_arguments(check)
    check.add_argument("--checker", dest="checkers", action="append", default=[])
    check.add_argument("--format", choices=("text", "json"), default="text")

    ledger = subparsers.add_parser("ledger", help="verify or summarize evidence")
    ledger_commands = ledger.add_subparsers(dest="ledger_command", required=True)
    ledger_commands.add_parser("verify")
    ledger_commands.add_parser("summary")

    knowledge = subparsers.add_parser("knowledge", help="inspect and sync Knowledge freshness")
    knowledge_commands = knowledge.add_subparsers(dest="knowledge_command", required=True)
    knowledge_status_parser = knowledge_commands.add_parser("status")
    knowledge_status_parser.add_argument("--format", choices=("text", "json"), default="text")
    knowledge_sync_parser = knowledge_commands.add_parser("sync")
    knowledge_sync_parser.add_argument("--card", dest="cards", action="append", required=True)
    knowledge_sync_parser.add_argument("--actor", required=True)
    knowledge_sync_parser.add_argument("--reason", required=True)
    knowledge_sync_parser.add_argument("--format", choices=("text", "json"), default="text")

    govern = subparsers.add_parser("govern", help="ingest, update, and retrieve project governance knowledge")
    govern_commands = govern.add_subparsers(dest="govern_command", required=True)
    govern_ingest = govern_commands.add_parser("ingest")
    govern_ingest.add_argument("--actor", required=True)
    govern_ingest.add_argument("--reason", required=True)
    govern_ingest.add_argument("--format", choices=("text", "json"), default="text")
    govern_pending = govern_commands.add_parser("pending")
    govern_pending.add_argument("--format", choices=("text", "json"), default="text")
    govern_settle = govern_commands.add_parser("settle")
    govern_settle.add_argument("--actor", required=True)
    govern_settle.add_argument("--reason", required=True)
    govern_settle.add_argument("--format", choices=("text", "json"), default="text")
    govern_apply = govern_commands.add_parser("apply")
    govern_apply.add_argument("--action", required=True, choices=("add", "update", "remove"))
    govern_apply.add_argument("--kind", default="card", choices=("card",))
    govern_apply.add_argument("--id", dest="card_id", required=True)
    govern_apply.add_argument("--actor", required=True)
    govern_apply.add_argument("--reason", required=True)
    govern_apply.add_argument("--type", dest="card_type", default="knowledge")
    govern_apply.add_argument("--title", default="")
    govern_apply.add_argument("--summary", default="")
    govern_apply.add_argument("--include", dest="includes", action="append", default=[])
    govern_apply.add_argument("--provides", action="append", default=None, help="Reusable capability (货架); repeatable. Omit to keep existing.")
    govern_apply.add_argument("--conventions", default=None, help="写法约定 for this module. Omit to keep existing.")
    govern_apply.add_argument("--budget-lines", type=int, default=None, help="Soft budget: max lines of code for this room. 0 = no budget.")
    govern_apply.add_argument("--optional", action="store_true", default=None, help="Mark floor card as optional (advisory, doesn't block verify).")
    govern_apply.add_argument("--maturity", default=None, help="Maturity level: L0, L1, L2, or L3.")
    govern_apply.add_argument("--format", choices=("text", "json"), default="text")
    govern_retrieve = govern_commands.add_parser("retrieve")
    _add_slice_arguments(govern_retrieve)
    govern_retrieve.add_argument("--format", choices=("text", "json"), default="text")

    household = govern_commands.add_parser("household", help="register a directory jurisdiction, never a README proxy")
    for field in ("id", "title", "summary", "capability", "implementation", "actor", "reason"):
        household.add_argument("--" + field, required=True)
    for field in ("include", "exclude", "floor"):
        household.add_argument("--" + field, action="append", default=[])
    # None means "keep the existing values"; an explicit flag replaces them.
    household.add_argument("--entrypoint", action="append", default=None)
    household.add_argument("--checker", action="append", default=None)
    household.add_argument("--status", choices=("current", "legacy", "retired"), default="current")
    household.add_argument("--grain", choices=("subtree", "directory", "module", "file"), default="", help="file=文件粒度户口：include 须为精确文件路径（t59 删除门）")
    household.add_argument("--meaning", choices=("none", "named"), default="")
    household.add_argument("--contract", choices=("none", "partial", "machine"), default="")
    household.add_argument("--decider", choices=("none", "machine", "confirm"), default="")
    household.add_argument("--span", default="", help="未打标 / 整夹一张 / 一文件一张")
    household.add_argument("--replaced-by", default="")
    household.add_argument("--provides", action="append", default=None, help="Reusable capability this room offers (货架); repeatable. Omit to keep existing.")
    household.add_argument("--conventions", default=None, help="写法约定 for this room. Omit to keep existing.")
    household.add_argument("--budget-lines", type=int, default=None, help="Explicit line budget for this room (人工预算，优先于动态仓). Omit to keep existing; 0 clears.")
    household.add_argument("--command-json", help="implementation-specific checker argv as JSON")
    household.add_argument("--format", choices=("text", "json"), default="json")
    tighten = govern_commands.add_parser("tighten", help="monotonically tighten a directory household strategy")
    tighten.add_argument("--id", required=True)
    tighten.add_argument("--grain", choices=("subtree", "directory", "module"), default="")
    tighten.add_argument("--meaning", choices=("none", "named"), default="")
    tighten.add_argument("--contract", choices=("none", "partial", "machine"), default="")
    tighten.add_argument("--decider", choices=("none", "machine", "confirm"), default="")
    tighten.add_argument("--actor", required=True)
    tighten.add_argument("--reason", required=True)
    tighten.add_argument("--format", choices=("text", "json"), default="json")
    renew = govern_commands.add_parser("renew-exploring", help="keep an exploring household visible without claiming it is named")
    renew.add_argument("--id", required=True)
    renew.add_argument("--actor", required=True)
    renew.add_argument("--reason", required=True)
    renew.add_argument("--format", choices=("text", "json"), default="json")
    retire = govern_commands.add_parser("retire", help="mark a directory household leftover before deleting its bytes")
    retire.add_argument("--id", required=True)
    retire.add_argument("--replaced-by", default="")
    retire.add_argument("--actor", required=True)
    retire.add_argument("--reason", required=True)
    retire.add_argument("--format", choices=("text", "json"), default="json")
    retire_confirm = govern_commands.add_parser("retire-confirm", help="human fuse for irreversible leftover deletion")
    retire_confirm.add_argument("--id", required=True)
    retire_confirm.add_argument("--actor", required=True)
    retire_confirm.add_argument("--reason", required=True)
    retire_confirm.add_argument("--format", choices=("text", "json"), default="json")
    census = govern_commands.add_parser("census", help="inspect scope freshness; --record explicitly records a review")
    census.add_argument("--record", action="store_true")
    census.add_argument("--all", action="store_true")
    census.add_argument("--card", action="append", default=[])
    census.add_argument("--actor", default="")
    census.add_argument("--reason", default="")
    census.add_argument("--format", choices=("text", "json"), default="json")
    budget_recal = govern_commands.add_parser("budget-recalibrate", help="按普查实测重标动态房间预算（系统算，用户被告知）")
    budget_recal.add_argument("--actor", default="")
    budget_recal.add_argument("--reason", default="")
    budget_recal.add_argument("--format", choices=("text", "json"), default="text")
    cost_report_cmd = govern_commands.add_parser("cost-report", help="开发成本三腿仪表（高效/经济 MTok/有效），纯读账本，不折钱不拦截")
    cost_report_cmd.add_argument("--format", choices=("text", "json"), default="text")
    verify_budget = govern_commands.add_parser("verify-budget", help="按账本耗时历史重标验证成本预算（裸命令=预览表；带 --actor/--reason 才落盘）")
    verify_budget.add_argument("--actor", default="")
    verify_budget.add_argument("--reason", default="")
    verify_budget.add_argument("--format", choices=("text", "json"), default="text")
    span = govern_commands.add_parser("span", help="set a directory room's coverage tag: 未打标, 整夹一张, or 一文件一张")
    span.add_argument("--id", required=True)
    span.add_argument("--tag", required=True, help="未打标 / 整夹一张 / 一文件一张")
    span.add_argument("--actor", required=True)
    span.add_argument("--reason", required=True)
    span.add_argument("--format", choices=("text", "json"), default="json")
    enforcement = govern_commands.add_parser("household-gate")
    enforcement.add_argument("--mode", choices=("enforce", "observe"), required=True)
    enforcement.add_argument("--actor", required=True)
    enforcement.add_argument("--reason", required=True)
    enforcement.add_argument("--format", choices=("text", "json"), default="json")
    parallelism_cmd = govern_commands.add_parser("checker-parallelism", help="设置 floor checker 并行度（1=串行；checker 是独立子进程，可并行提速 verify）")
    parallelism_cmd.add_argument("--workers", type=int, required=True)
    parallelism_cmd.add_argument("--actor", required=True)
    parallelism_cmd.add_argument("--reason", required=True)
    parallelism_cmd.add_argument("--format", choices=("text", "json"), default="json")
    checker_cmd = govern_commands.add_parser("checker", help="create or adjust a policy checker (always / parse / timeout / command / stage)")
    checker_cmd.add_argument("--id", required=True)
    checker_cmd.add_argument("--always", choices=("on", "off"), default="")
    checker_cmd.add_argument("--parse", choices=("unittest", "none"), default="")
    checker_cmd.add_argument("--timeout", type=int, default=0)
    checker_cmd.add_argument("--command", dest="checker_command", default="", help='JSON argv array, e.g. ["python","-B","tests/suites.py","fast"]; creates the checker when the id is unknown')
    checker_cmd.add_argument("--stage", choices=("static", "floor", "boundary", "scenario"), default="")
    checker_cmd.add_argument("--bind", action="append", default=[], help="card id to bind the checker to (repeatable); required when creating")
    checker_cmd.add_argument("--budget-seconds", type=float, default=None, help="人工显式验证预算（秒）：>0 优先于动态预算仓；0=清除显式预算")
    checker_cmd.add_argument("--actor", required=True)
    checker_cmd.add_argument("--reason", required=True)
    checker_cmd.add_argument("--format", choices=("text", "json"), default="json")
    baseline_cmd = govern_commands.add_parser("test-baseline", help="record current unittest failures as the zero-regression baseline")
    baseline_cmd.add_argument("--checker", action="append", default=[])
    baseline_cmd.add_argument("--actor", required=True)
    baseline_cmd.add_argument("--reason", required=True)
    baseline_cmd.add_argument("--format", choices=("text", "json"), default="json")
    flatten_queue_cmd = govern_commands.add_parser(
        "flatten-queue",
        help="反向开发队列：src/ag2c 文件按热度×肥胖度（行数×提交数）排序",
    )
    flatten_queue_cmd.add_argument("--format", choices=("text", "json"), default="json")
    flatten_check_cmd = govern_commands.add_parser(
        "flatten-check",
        help="纯搬运门：stdin 统一 diff，新增非豁免行必须来自删除行",
    )
    flatten_check_cmd.add_argument("--format", choices=("text", "json"), default="json")
    flatten_split_cmd = govern_commands.add_parser(
        "flatten-split",
        help="拆分原语：抽出顶层符号到同目录新模块，源文件门面再导出",
    )
    flatten_split_cmd.add_argument("--source", required=True, help="源文件，相对仓库根，如 src/ag2c/tasks.py")
    flatten_split_cmd.add_argument("--dest", required=True, help="目标新文件，须与源同目录")
    flatten_split_cmd.add_argument("--name", action="append", default=[], help="要抽出的顶层函数/类/常量名，可重复")
    flatten_split_cmd.add_argument("--dry-run", action="store_true", help="只报告计划，不写文件")
    flatten_split_cmd.add_argument("--format", choices=("text", "json"), default="json")
    wdismiss_cmd = govern_commands.add_parser("warning-dismiss", help="撤销一条警告的累计计数（警告升级门的合法出口），带 actor/reason 落账本；计数从零重来")
    wdismiss_cmd.add_argument("--key", required=True, help="警告 key，与升级门报错中一致（如 check.suite-enrollment:seconds）")
    wdismiss_cmd.add_argument("--actor", required=True)
    wdismiss_cmd.add_argument("--reason", required=True)
    wdismiss_cmd.add_argument("--format", choices=("text", "json"), default="json")
    regulator_cmd = govern_commands.add_parser("regulator", help="configure the AI regulator (agent-review): endpoint / model / strict / enable")
    regulator_cmd.add_argument("--enable", choices=("on", "off"), default="")
    regulator_cmd.add_argument("--endpoint", default="")
    regulator_cmd.add_argument("--model", default="")
    regulator_cmd.add_argument("--worker-model", default="", help="被治理 worker 的模型名（9.10 安达信条款：与监管同族时拒绝配置）")
    regulator_cmd.add_argument("--allow-same-family", choices=("on", "off"), default="", help="显式豁免同族检测（进账本并大字警告）")
    regulator_cmd.add_argument("--api-key-env", default="")
    regulator_cmd.add_argument("--strict", choices=("on", "off"), default="")
    regulator_cmd.add_argument("--timeout", type=int, default=0)
    regulator_cmd.add_argument("--actor", required=True)
    regulator_cmd.add_argument("--reason", required=True)
    regulator_cmd.add_argument("--format", choices=("text", "json"), default="json")
    proxy_cmd = govern_commands.add_parser("proxy", help="L0 旗标与 L1 具名规则：auto_settle / auto_census / auto_warning，--grant 写 rules，不代理 merge")
    proxy_cmd.add_argument("--auto-settle", choices=("on", "off"), default="")
    proxy_cmd.add_argument("--auto-census", choices=("on", "off"), default="")
    proxy_cmd.add_argument("--auto-warning", choices=("on", "off"), default="")
    proxy_cmd.add_argument("--rule-id", default="", help="L1 规则 id，配合 --grant")
    proxy_cmd.add_argument("--flag", default="", help="L1 规则绑定的旗标：auto_settle|auto_census|auto_warning")
    proxy_cmd.add_argument("--grant", action="store_true", help="把具名规则写入 policy.proxy.rules 并落 proxy-grant")
    proxy_cmd.add_argument("--actor", required=True)
    proxy_cmd.add_argument("--reason", required=True)
    proxy_cmd.add_argument("--format", choices=("text", "json"), default="json")
    trunk_cmd = govern_commands.add_parser("trunk", help="登记/变更正主的登记主干分支（start/finish 前置守卫以此为准）")
    trunk_cmd.add_argument("--branch", required=True)
    trunk_cmd.add_argument("--actor", required=True)
    trunk_cmd.add_argument("--reason", required=True)
    trunk_cmd.add_argument("--format", choices=("text", "json"), default="json")
    dismiss_cmd = govern_commands.add_parser("hazard-dismiss", help="豁免一条危房（审过判定不拆），带理由与日落期，到期自动重现")
    dismiss_cmd.add_argument("target", help="危房目标，与看板上一致（如 tests/support.py）")
    dismiss_cmd.add_argument("--kind", required=True, choices=("hollow", "duplicate", "budget", "stale"))
    dismiss_cmd.add_argument("--days", type=int, default=90, help="日落期天数，到期自动重现（默认 90）")
    dismiss_cmd.add_argument("--actor", required=True)
    dismiss_cmd.add_argument("--reason", required=True)
    dismiss_cmd.add_argument("--format", choices=("text", "json"), default="json")
    anchor_cmd = govern_commands.add_parser("trust-anchor", help="写离线签名锚：ledger+policy digest 快照，signature 空串待签")
    anchor_cmd.add_argument("--actor", required=True)
    anchor_cmd.add_argument("--reason", required=True)
    anchor_cmd.add_argument("--format", choices=("text", "json"), default="json")
    sandbox_cmd = govern_commands.add_parser("sandbox", help="只读政策沙盘：重放候选规则，不写 policy、不追加账本")
    sandbox_cmd.add_argument("--scenario", required=True, help="l2-to-l3：AG2K L2→L3 分拣标准")
    sandbox_cmd.add_argument("--format", choices=("text", "json"), default="json")

    doctor = subparsers.add_parser("doctor", help="check configuration, activation, tools, index, and ledger")
    doctor.add_argument("--repair", action="store_true", help="restore the Skill, Git guard, activation, and index")
    doctor.add_argument("--skill-destination", type=Path)
    _add_harness_arguments(doctor)

    canary = subparsers.add_parser("canary", help="plant a known defect and verify the gate catches it")
    canary.add_argument("--actor", required=True)
    canary.add_argument("--reason", required=True)
    canary.add_argument("--mode", choices=("gate", "mutation"), default="gate", help="gate: 投放失败用例验门禁；mutation: 改坏一行产品代码验测试有牙")
    canary.add_argument("--target", default=None, help="mutation 模式专用：定向变异指定文件（path_spec 或仓内相对路径），用于危房销案复跑")
    canary.add_argument("--format", choices=("text", "json"), default="json")
    return parser


def _canary(manifest, policy, *, actor: str, reason: str, output_format: str = "json") -> int:
    """Plant a known defect in a governed directory and verify the gate catches it.

    The canary proves the gate still bites: if the defect passes verification,
    the governance loop is broken and the result is canary-failed.

    The defect is a failing unittest planted under ``tests/`` so the always-on
    test checker must catch it. The index snapshot is refreshed right after
    planting (and again after cleanup) so the freshness gate evaluates the
    canary instead of rejecting the canary's own footprint. The same applies
    to the census: the planted file changes the room's scope digest, so the
    canary attests exactly the rooms it made stale — never pre-existing drift.
    """
    from .checks import run_checks
    from .household_commands import review_census
    from .households import census_report
    from .index import build_index
    from .slicer import compile_slice

    target = manifest.targets[0] if manifest.targets else None
    if target is None:
        print("AG2C error: no targets in manifest", file=sys.stderr)
        return 2
    target_root = manifest.target_root(target.target_id)
    tests_dir = target_root / "tests"
    if not tests_dir.is_dir():
        print("AG2C error: canary requires a tests/ directory in the governed target", file=sys.stderr)
        return 2
    # Plant a failing test that any test-discovery checker must catch.
    canary_path = tests_dir / "test_ag2c_canary.py"
    canary_content = (
        '"""AG2C canary: known defect for gate validation."""\n'
        "import unittest\n\n\n"
        "class CanaryTest(unittest.TestCase):\n"
        "    def test_canary_broken(self):\n"
        '        self.fail("canary: this defect must be caught")\n'
    )
    canary_rel = f"{target.target_id}:tests/test_ag2c_canary.py"

    def _stale_households() -> set[str]:
        report = census_report(manifest, policy)
        return {item["id"] for item in report["households"] if item["freshness"] != "current"}

    pre_stale = _stale_households()
    canary_caused: set[str] = set()
    try:
        canary_path.write_text(canary_content, encoding="utf-8")
        # Refresh the index so the freshness gate sees the canary as the
        # current state instead of rejecting the canary's own footprint.
        build_index(manifest, policy)
        # The planted file also changes the room's scope digest; attest only
        # the rooms the canary itself made stale, never pre-existing drift.
        canary_caused = _stale_households() - pre_stale
        if canary_caused:
            review_census(
                target_root,
                card_ids=sorted(canary_caused),
                all_cards=False,
                actor=actor,
                reason=f"canary footprint: attest self-planted {canary_rel}",
            )
        # Build a minimal slice for the canary file.
        entry_slice = compile_slice(
            manifest,
            policy,
            path_specs=[canary_rel],
            contract_specs=[],
            goal="canary: gate validation",
            all_mode=False,
        )
        report = run_checks(
            manifest,
            policy,
            entry_slice,
            all_mode=False,
            ledger_path=manifest.ledger_path,
            task_id="canary",
        )
        # The canary passes if any checker failed (gate caught the defect).
        failed = [r for r in report["results"] if r["status"] not in {"passed", "skipped"}]
        caught = bool(failed)
        result = {
            "schema": "ag2c.canary.v1",
            "canary": "passed" if caught else "failed",
            "caught_by": [r["id"] for r in failed],
            "checkers_run": len(report["results"]),
            "actor": actor,
            "reason": reason,
        }
        from .ledger import append_event
        append_event(manifest.ledger_path, "canary", result)
        if output_format == "json":
            print(_json(result))
        else:
            label = "金丝雀存活（门禁有效）" if caught else "金丝雀死亡（门禁失效！）"
            print(f"{label}: {len(failed)}/{len(report['results'])} 检查拦截")
        return 0 if caught else 1
    finally:
        canary_path.unlink(missing_ok=True)
        try:
            # Restore the snapshot so later governance actions stay unblocked.
            build_index(manifest, policy)
            # Re-attest the rooms the canary attested while planted: removing
            # the file reverts their scope digest, which would otherwise leave
            # them stale against the canary-era census record.
            restored = _stale_households() & canary_caused
            if restored:
                review_census(
                    target_root,
                    card_ids=sorted(restored),
                    all_cards=False,
                    actor=actor,
                    reason="canary cleanup: re-attest restored rooms",
                )
        except Exception:
            print("AG2C warning: index refresh failed after canary cleanup", file=sys.stderr)


def _doctor(manifest, policy) -> int:
    from .enrollment import activation_status
    from .gitops import which_command

    issues: list[str] = []
    issues.extend(activation_status(manifest.project_root)["issues"])
    for target in manifest.targets:
        if not manifest.target_root(target.target_id).is_dir():
            issues.append(f"missing target directory: {target.target_id}:{manifest.target_root(target.target_id)}")
    for checker in policy.checkers:
        if which_command(checker.command[0]) is None:
            issues.append(f"checker executable is not available: {checker.checker_id}:{checker.command[0]}")
    current_errors = verify_freshness(manifest, policy, index_path(manifest))
    issues.extend(current_errors)
    issues.extend(f"ledger: {error}" for error in verify_ledger(manifest.ledger_path))
    if issues:
        print("AG2C doctor found issues:")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print("AG2C activation, configuration, tools, index, and ledger are current.")
    return 0


def _print_evidence(report: dict[str, Any]) -> None:
    coverage = report["coverage"]
    print(f"AutoGovern2Code evidence: {report['project']}")
    print(f"Governance: {'active' if report['managed'] else 'needs repair'}")
    print(f"Evidence chain: {'valid' if report['ledger_valid'] else 'invalid'}")
    print(
        f"Coverage: {coverage['level']} / {coverage['area_count']} areas / "
        f"{coverage['checker_count']} trusted checks / {coverage['strategy']} fallback / "
        f"verification {coverage.get('verification_growth') or 'unsplit'}"
    )
    if coverage.get("verification_growth_summary"):
        print(f"Verification growth: {coverage['verification_growth']} — {coverage['verification_growth_summary']}")
    if not report["tasks"]:
        print("No governed tasks have been recorded yet.")
        return
    for task in report["tasks"]:
        print(f"\n{task['goal']} [{task['id']}]")
        delivery = task.get("delivery") or {}
        if delivery.get("outcome"):
            print(f"Delivered: {delivery['outcome']}")
        if delivery.get("kind"):
            print(f"Change: {delivery['kind']}")
        if delivery.get("request") and delivery.get("request") != delivery.get("outcome"):
            print(f"Requested: {delivery['request']}")
        print(f"Management: {task['management_result']}")
        print(f"Worktree: {(task.get('worktree') or {}).get('lifecycle', task['state'])}")
        print(f"Files changed: {len(task['changed_files'])}")
        print(f"Checks: {task['checks_passed']}/{task['checks_run']} passed")
        print(f"Verification attempts: {task['verification_attempts']}")
        if task["correction_proven"]:
            print(f"AI correction: proven after {task['failed_attempts']} failed attempt(s)")
        elif task["failed_attempts"]:
            print(f"AI correction: not yet proven ({task['failed_attempts']} failed attempt(s))")
        else:
            print("AI correction: not required")
        print(f"Blocked unsafe actions: {len(task['blocked_actions'])}")
        print(f"Local evidence: {task['local_evidence']['status']}")
        if task["result"]:
            print(f"Merged commit: {task['result']['commit']}")
        print(f"Process evidence: {'complete' if task['evidence_complete'] else 'incomplete'}")
        product = task.get("product") or report.get("product") or {}
        print(f"Product: {product.get('status', 'undeclared')}")
        if product.get("summary"):
            print(f"Product detail: {product['summary']}")

from .cli_main import main
