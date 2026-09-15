"""Extracted by flatten-split."""
from __future__ import annotations
import json
import sys
from pathlib import Path
from .checks import run_checks
from .config import discover_manifest, load_manifest, load_policy
from .errors import AG2CError
from .index import build_index, findings, index_path, summary, verify_freshness
from .ledger import ledger_summary, verify_ledger
from .knowledge import knowledge_status, sync_knowledge
from .render import render_slice_markdown
from .acceptance import coverage_view
from .cli import _canary, _configure_stdio, _doctor, _json, _loaded, _print_evidence, _slice_from_args, _write_output, build_parser

def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "setup":
            from .enrollment import setup_project

            print(
                _json(
                    setup_project(
                        args.project,
                        project_id=args.project_id,
                        skill_root=args.skill_destination,
                        harnesses=tuple(args.harnesses) if args.harnesses else None,
                        run_first_drill=True,
                    )
                )
            )
            return 0
        if args.command == "enroll":
            from .enrollment import enroll_project

            print(
                _json(
                    enroll_project(
                        args.path,
                        project_id=args.project_id,
                        harnesses=tuple(args.harnesses) if args.harnesses else None,
                        run_first_drill=True,
                    )
                )
            )
            return 0
        if args.command == "activate":
            from .enrollment import activate_project

            print(_json(activate_project(args.path, harnesses=tuple(args.harnesses) if args.harnesses else None)))
            return 0
        if args.command == "upgrade":
            from .enrollment import upgrade_project

            print(
                _json(
                    upgrade_project(
                        args.path,
                        skill_root=args.skill_destination,
                        harnesses=tuple(args.harnesses) if args.harnesses else None,
                    )
                )
            )
            return 0
        if args.command == "migrate":
            from .enrollment import migrate_project

            print(
                _json(
                    migrate_project(
                        args.path,
                        skill_root=args.skill_destination,
                        harnesses=tuple(args.harnesses) if args.harnesses else None,
                    )
                )
            )
            return 0
        if args.command == "skill":
            from .harnesses import install_skills, packaged_skills_report, remove_skills, skill_entry_prompt

            if args.skill_command == "prompt":
                print(skill_entry_prompt(project=args.project), end="")
                return 0
            if args.skill_command == "version":
                print(_json(packaged_skills_report()))
                return 0
            print(
                _json(
                    (
                        install_skills(
                            args.destination,
                            tuple(args.harnesses) if args.harnesses else None,
                        )
                        if args.skill_command == "install"
                        else remove_skills(
                            args.destination,
                            tuple(args.harnesses) if args.harnesses else None,
                        )
                    )
                )
            )
            return 0
        if args.command == "mcp":
            from .mcp_server import (
                install_mcp_clients,
                mcp_config_snippet,
                mcp_connect_prompt,
                mcp_health,
                mcp_toml_block,
                serve_mcp_stdio,
            )

            action = args.mcp_command or "serve"
            if action == "install":
                print(_json(install_mcp_clients()))
                return 0
            if action == "config":
                print(
                    _json(
                        {
                            "json": mcp_config_snippet(placeholders=True),
                            "toml": mcp_toml_block(placeholders=True),
                        }
                    )
                )
                return 0
            if action == "prompt":
                print(mcp_connect_prompt())
                return 0
            if action == "health":
                print(_json(mcp_health(handshake=True)))
                return 0
            return serve_mcp_stdio()
        if args.command == "project":
            from .management import add_project, managed_projects, project_status, stop_managing

            if args.project_command == "list":
                projects = managed_projects()
                if args.format == "json":
                    print(_json(projects))
                else:
                    if not projects:
                        print("No projects are managed by AutoGovern2Code.")
                    for item in projects:
                        print(f"[{item['state']}] {item['name']} - {item['root']}")
                return 0
            if args.project_command == "add":
                print(_json(add_project(args.path)))
                return 0
            if args.project_command == "status":
                result = project_status(args.path)
                print(_json(result))
                return 0 if result["managed"] else 1
            print(_json(stop_managing(args.path, remove_data=args.project_command == "uninstall" or bool(getattr(args, "remove_data", False)))))
            return 0
        if args.command == "desktop":
            from ag2c_gui.desktop import serve_desktop

            return serve_desktop(port=args.port, token=args.token)
        if args.command == "guard":
            from .enrollment import activation_status, guard_pre_commit

            if args.guard_command == "pre-commit":
                return guard_pre_commit(Path.cwd())
            status = activation_status(Path.cwd())
            print(_json(status))
            return 0 if status["managed"] else 1
        if args.command == "task":
            from .tasks import amend_portrait, declare_front_back, declare_full_scan, finish_task, start_task, task_record, verify_task
            from .task_orient import abandon_task, list_tasks, orient_task, refresh_task

            if args.task_command == "start":
                coordinate_declaration: dict[str, str] = {}
                for item in args.coordinate or []:
                    dim, sep, value = str(item).partition("=")
                    if not sep:
                        raise AG2CError(f"--coordinate expects DIM=VALUE: {item!r}")
                    dim = dim.strip()
                    if dim in coordinate_declaration:
                        raise AG2CError(f"--coordinate repeated for dimension: {dim}")
                    coordinate_declaration[dim] = value.strip()
                print(
                    _json(
                        start_task(
                            Path.cwd(),
                            goal=args.goal,
                            path_specs=list(args.paths),
                            contract_specs=list(args.contracts),
                            all_mode=bool(args.all),
                            task_id=args.task_id,
                            worktree_root=args.worktree_root,
                            portrait=args.portrait,
                            touches_verification=bool(args.touches_verification),
                            coordinates=coordinate_declaration,
                        )
                    )
                )
                return 0
            if args.task_command == "verify":
                result = verify_task(Path.cwd())
                print(_json(result))
                return 0 if result["passed"] else 1
            if args.task_command == "declare":
                if getattr(args, "trust_base", False):
                    if getattr(args, "full_scan", False):
                        raise AG2CError("declare --trust-base and --full-scan are mutually exclusive")
                    from .trust_base import declare_trust_base

                    print(_json(declare_trust_base(Path.cwd(), reason=args.reason, why=args.why, risk=args.risk, rollback=args.rollback, verify=args.verify_how)))
                elif getattr(args, "full_scan", False):
                    print(_json(declare_full_scan(Path.cwd(), reason=args.reason)))
                else:
                    print(_json(declare_front_back(Path.cwd(), reason=args.reason)))
                return 0
            if args.task_command == "approve":
                if not getattr(args, "trust_base", False):
                    raise AG2CError("task approve requires --trust-base")
                from .trust_base import approve_trust_base

                print(_json(approve_trust_base(Path.cwd(), actor=args.actor, reason=args.reason)))
                return 0
            if args.task_command == "amend-portrait":
                portrait_text = str(args.portrait or "")
                if args.portrait_file is not None:
                    if portrait_text.strip():
                        raise AG2CError("--portrait and --portrait-file are mutually exclusive")
                    try:
                        portrait_text = args.portrait_file.read_text(encoding="utf-8")
                    except OSError as exc:
                        raise AG2CError(f"cannot read portrait file {args.portrait_file}: {exc}") from exc
                print(_json(amend_portrait(Path.cwd(), portrait=portrait_text, actor=args.actor, reason=args.reason)))
                return 0
            if args.task_command == "list":
                records = list_tasks(Path.cwd())
                if args.format == "json":
                    print(_json(records))
                elif not records:
                    print("No governed tasks have been recorded yet.")
                else:
                    labels = {
                        "in-progress": "constructing",
                        "verified-unmerged": "verified, not merged",
                        "verified-stale": "verified bytes changed",
                        "diverged": "canonical moved",
                        "missing": "worktree missing",
                        "completed": "merged",
                        "abandoned": "abandoned",
                    }
                    for item in records:
                        lifecycle = str((item.get("worktree") or {}).get("lifecycle", item["state"]))
                        print(f"[{lifecycle}] {item['id']} - {item['goal']}")
                        print(f"  {labels.get(lifecycle, item['state'])}: {(item.get('worktree') or {}).get('path', '')}")
                return 0
            if args.task_command == "orient":
                print(_json(orient_task(Path.cwd(), args.task)))
                return 0
            if args.task_command == "refresh":
                print(_json(refresh_task(Path.cwd(), args.task)))
                return 0
            if args.task_command == "abandon":
                print(_json(abandon_task(Path.cwd(), args.task, reason=args.reason)))
                return 0
            if args.task_command == "finish":
                estimated = None
                raw_tokens = str(getattr(args, "estimated_tokens", "") or "").strip()
                if raw_tokens:
                    try:
                        estimated = json.loads(raw_tokens)
                    except json.JSONDecodeError as exc:
                        raise AG2CError(f"--estimated-tokens must be JSON: {exc}") from exc
                finished = finish_task(
                    Path.cwd(),
                    args.task,
                    message=args.message,
                    proof=args.proof,
                    sessions=getattr(args, "sessions", None),
                    estimated_tokens=estimated,
                )
                print(_json(finished))
                for hint in finished.get("hints") or []:
                    print(f"收尾提示: {hint}", file=sys.stderr)
                return 0
            print(_json(task_record(Path.cwd(), args.task)))
            return 0
        if args.command == "evidence":
            from .tasks import evidence

            report = evidence(Path.cwd(), args.task)
            if args.format == "json":
                print(_json(report))
            else:
                _print_evidence(report)
            evidence_ok = all(task["management_result"] in {"successful", "abandoned"} for task in report["tasks"])
            return 0 if report["managed"] and report["ledger_valid"] and evidence_ok else 1
        if args.command == "doctor" and args.repair:
            from .enrollment import repair_project

            repair_project(
                Path.cwd(),
                skill_root=args.skill_destination,
                harnesses=tuple(args.harnesses) if args.harnesses else None,
            )
        if args.command == "doctor" and not args.repair:
            from .errors import RELOCATED_PROJECT, STALE_EXTERNAL_STORE
            from .storage import BINDING_RELOCATED, BINDING_STALE, resolve_enrollment_binding

            binding = resolve_enrollment_binding(Path.cwd())
            if binding["state"] == BINDING_STALE:
                print("AG2C doctor found issues:")
                print(f"- {STALE_EXTERNAL_STORE}: configured AG2C store is missing on this computer")
                print("Run `ag2c doctor --repair` or add the project again to restore this computer's store.")
                return 1
            if binding["state"] == BINDING_RELOCATED:
                print("AG2C doctor found issues:")
                print(f"- {RELOCATED_PROJECT}: Git still points at another computer's AG2C store")
                print("Run `ag2c doctor --repair` to rebind the store found on this computer.")
                return 1
        if args.command == "ci":
            from .receipts import verify_commit_receipt

            report = verify_commit_receipt(Path.cwd(), args.commit, rerun=bool(args.rerun))
            if args.format == "json":
                print(_json(report))
            else:
                print(f"Local evidence: {report['local_evidence']}")
                print(f"Commit: {report['commit']}")
                print(f"Trusted checks recorded: {report['checks']}")
                print(f"Check rerun: {report['rerun']}")
            return 0
        if args.command == "govern" and args.govern_command in {
            "flatten-queue",
            "flatten-check",
            "flatten-bill",
            "flatten-split",
            "flatten-glue",
            "flatten-door",
            "flatten-cut",
        }:
            if args.govern_command == "flatten-queue":
                from .flatten import FLATTEN_QUEUE_SCHEMA, flatten_queue

                items = flatten_queue(Path.cwd(), under=str(getattr(args, "under", "") or "") or None)
                result = {"schema": FLATTEN_QUEUE_SCHEMA, "items": items}
                if args.format == "text":
                    if not items:
                        print("flatten-queue: empty")
                        return 0
                    for item in items:
                        print(f"{item['score']}\t{item['lines']} lines\t{item['heat']} commits\t{item['path']}")
                    return 0
                print(_json(result))
                return 0
            if args.govern_command == "flatten-check":
                from .flatten import FLATTEN_CHECK_SCHEMA, pure_move_violations

                diff = sys.stdin.read()
                violations = pure_move_violations(diff)
                result = {"schema": FLATTEN_CHECK_SCHEMA, "violations": violations}
                if args.format == "text":
                    if not violations:
                        print("flatten-check: pass")
                        return 0
                    print("flatten-check: fail")
                    for item in violations:
                        print(item)
                    return 1
                print(_json(result))
                return 1 if violations else 0
            if args.govern_command == "flatten-bill":
                from .flatten import flatten_bill, format_flatten_bill

                bill = flatten_bill(sys.stdin.read())
                if args.format == "json":
                    print(_json(bill))
                else:
                    print(format_flatten_bill(bill), end="")
                return 0
            if args.govern_command == "flatten-split":
                from .flatten import flatten_split

                result = flatten_split(
                    Path.cwd(),
                    source=args.source,
                    dest=args.dest,
                    names=list(args.name),
                    dry_run=bool(args.dry_run),
                )
                if args.format == "text":
                    print(f"flatten-split: {result['source']} -> {result['dest']} ({', '.join(result['names'])})")
                    if result.get("dry_run"):
                        print("dry-run")
                    return 0
                print(_json(result))
                return 0
            if args.govern_command == "flatten-glue":
                from .flatten import flatten_glue

                result = flatten_glue(Path.cwd(), str(args.file))
                if args.format == "text":
                    print("胶水" if result["glue"] else "不是胶水")
                    for reason in result.get("reasons") or []:
                        print(reason)
                    return 0
                print(_json(result))
                return 0
            if args.govern_command == "flatten-door":
                from .flatten import flatten_door

                result = flatten_door(Path.cwd(), old=str(args.old), side=str(args.side), names=list(args.name))
                if args.format == "text":
                    print("门牌改掉了" if result["cut"] else "门牌没改")
                    print(result.get("reason") or "")
                    return 0
                print(_json(result))
                return 0
            from .flatten import flatten_cut

            result = flatten_cut(
                Path.cwd(),
                old=str(args.old),
                side=str(args.side),
                names=list(args.name),
                write=bool(args.write),
            )
            if args.format == "text":
                print("预览" if not result["write"] else "已写盘")
                print(result.get("reason") or "")
                for item in result.get("planned") or []:
                    print(f"{item['path']}: {item['before']} -> {item['after']}")
                return 0
            print(_json(result))
            return 0
        manifest, policy = _loaded(args)
        if args.command == "knowledge":
            if args.knowledge_command == "status":
                statuses = knowledge_status(manifest, policy)
                if args.format == "json":
                    print(_json(statuses))
                elif not statuses:
                    print("No Knowledge cards are configured.")
                else:
                    for item in statuses:
                        reasons = f" ({', '.join(item['reasons'])})" if item["reasons"] else ""
                        print(
                            f"[{item['status']}] {item['id']} - {item['title']} "
                            f"(source: {item['source_status']}; assertion: {item['assertion_status']}){reasons}"
                        )
                return 0 if all(item["status"] not in {"stale", "conflict"} for item in statuses) else 1
            result = sync_knowledge(
                manifest,
                policy,
                card_ids=list(args.cards),
                actor=args.actor,
                reason=args.reason,
            )
            if args.format == "json":
                print(_json(result))
            else:
                print(f"Synced Knowledge: {', '.join(result['cards'])}")
                print(f"Actor: {result['actor']}")
                print(f"Reason: {result['reason']}")
                print(f"Ledger event: {result['ledger_event_digest']}")
            return 0
        if args.command == "govern":
            from .govern import apply_change, ingest_project, pending_updates, retrieve_guidance, settle_pending

            if args.govern_command in {"household", "census", "household-gate", "checker-parallelism", "tighten", "renew-exploring", "retire", "retire-confirm", "span"}:
                from .household_commands import (
                    confirm_retirement,
                    read_census,
                    register_household,
                    renew_exploring,
                    retire_household,
                    review_census,
                    set_checker_parallelism,
                    set_household_enforcement,
                    set_household_span,
                    tighten_household,
                )

                if args.govern_command == "household":
                    result = register_household(Path.cwd(), card_id=args.id, title=args.title, summary=args.summary, includes=args.include, excludes=args.exclude, floors=args.floor, capability=args.capability, implementation=args.implementation, status=args.status, replaced_by=args.replaced_by, entrypoints=args.entrypoint, checkers=args.checker, command=json.loads(args.command_json) if args.command_json else None, grain=args.grain, meaning=args.meaning, contract=args.contract, decider=args.decider, span=args.span, provides=args.provides, conventions=args.conventions, budget_lines=args.budget_lines, actor=args.actor, reason=args.reason)
                elif args.govern_command == "household-gate":
                    result = set_household_enforcement(Path.cwd(), enabled=args.mode == "enforce", actor=args.actor, reason=args.reason)
                elif args.govern_command == "checker-parallelism":
                    result = set_checker_parallelism(Path.cwd(), workers=args.workers, actor=args.actor, reason=args.reason)
                elif args.govern_command == "tighten":
                    result = tighten_household(Path.cwd(), card_id=args.id, grain=args.grain, meaning=args.meaning, contract=args.contract, decider=args.decider, actor=args.actor, reason=args.reason)
                elif args.govern_command == "renew-exploring":
                    result = renew_exploring(Path.cwd(), card_id=args.id, actor=args.actor, reason=args.reason)
                elif args.govern_command == "retire":
                    result = retire_household(Path.cwd(), card_id=args.id, replaced_by=args.replaced_by, actor=args.actor, reason=args.reason)
                elif args.govern_command == "retire-confirm":
                    result = confirm_retirement(Path.cwd(), card_id=args.id, actor=args.actor, reason=args.reason)
                elif args.govern_command == "span":
                    result = set_household_span(Path.cwd(), card_id=args.id, span=args.tag, actor=args.actor, reason=args.reason)
                else:
                    result = review_census(Path.cwd(), card_ids=args.card, all_cards=args.all, actor=args.actor, reason=args.reason) if args.record else read_census(Path.cwd())
                print(_json(result))
                return 0
            if args.govern_command == "ingest":
                result = ingest_project(Path.cwd(), actor=args.actor, reason=args.reason)
            elif args.govern_command == "pending":
                result = pending_updates(Path.cwd())
            elif args.govern_command == "settle":
                result = settle_pending(Path.cwd(), actor=args.actor, reason=args.reason)
            elif args.govern_command == "budget-recalibrate":
                from .budgets import recalibrate_budgets
                from .config import discover_manifest, load_manifest, load_policy

                root = Path.cwd()
                manifest = load_manifest(discover_manifest(root), project_root=root)
                # 裸命令（无 --actor/--reason）= 预览：只算表不落盘不写账本；
                # 真正重标带 --actor/--reason（治理写入纪律）。
                dry_run = not (args.actor.strip() and args.reason.strip())
                result = recalibrate_budgets(manifest, load_policy(manifest), actor=args.actor, reason=args.reason, dry_run=dry_run)
                if args.format == "text":
                    rows = result.get("rooms") or []
                    if not rows:
                        print("没有需要动态预算的房间（空房间或全部人工显式预算）。")
                    for row in rows:
                        print(f"{row['room']}: 实测 {row['measured_lines']} 行，预算 {row['budget_lines']} 行（{row['action']}）")
                    if dry_run and rows:
                        print("（预览：未落盘。带 --actor/--reason 重标才写入预算仓与账本）")
                    return 0
            elif args.govern_command == "cost-report":
                from .config import discover_manifest, load_manifest
                from .token import cost_report

                root = Path.cwd()
                manifest = load_manifest(discover_manifest(root), project_root=root)
                result = cost_report(manifest)
                if args.format == "json":
                    print(_json(result))
                    return 0
                eff = result["efficiency"]
                eco_r = result["economy"]["regulator"]
                eco_s = result["economy"]["self_report"]
                fx = result["effectiveness"]

                def _pct(value):
                    return "n/a" if value is None else f"{value * 100:.1f}%"

                print(
                    f"高效  任务 {eff['tasks']}  verify {eff['verify_runs']}  "
                    f"轮次/任务 {eff['rounds_per_task'] if eff['rounds_per_task'] is not None else 'n/a'}  "
                    f"均时长 {eff['mean_task_seconds'] if eff['mean_task_seconds'] is not None else 'n/a'}s  "
                    f"失败率 {_pct(eff['verify_failure_rate'])}"
                )
                print(
                    f"经济  监管 {eco_r['mtok']} MTok（input {eco_r['input']} / output {eco_r['output']}）  "
                    f"自报 {eco_s['mtok']} MTok（INFERRED）"
                )
                print(
                    f"有效  一次通过率 {_pct(fx['first_pass_rate'])}  "
                    f"监管驳回率 {_pct(fx['regulator_reject_rate'])}  "
                    f"交付后修复 {fx['post_delivery_fixes']}"
                )
                return 0
            elif args.govern_command == "verify-timing":
                from .config import discover_manifest, load_manifest
                from .verify_costs import checker_timing_report, format_timing_text

                root = Path.cwd()
                manifest = load_manifest(discover_manifest(root), project_root=root)
                report = checker_timing_report(manifest)
                if args.format == "json":
                    print(_json(report))
                    return 0
                print(format_timing_text(report))
                return 0
            elif args.govern_command == "verify-budget":
                from .config import discover_manifest, load_manifest, load_policy
                from .verify_costs import recalibrate_verify_budgets

                root = Path.cwd()
                manifest = load_manifest(discover_manifest(root), project_root=root)
                # 与 budget-recalibrate 同一告知渠道模式：裸命令 = 预览（只算表
                # 不落盘不写账本）；真正重标带 --actor/--reason（治理写入纪律）。
                dry_run = not (args.actor.strip() and args.reason.strip())
                result = recalibrate_verify_budgets(manifest, load_policy(manifest), actor=args.actor, reason=args.reason, dry_run=dry_run)
                if args.format == "text":
                    rows = result.get("checkers") or []
                    if not rows:
                        print("没有可预算的 checker（账本里还没有 check-run 耗时记录，或全部人工显式预算）。")
                    for row in rows:
                        print(f"{row['checker']}: 实测 {row['measured_seconds']}s（近5次最大），预算 {row['budget_seconds']:.0f}s（{row['action']}）")
                    if dry_run and rows:
                        print("（预览：未落盘。带 --actor/--reason 重标才写入预算仓与账本）")
                    return 0
            elif args.govern_command == "checker":
                from .govern import update_checker

                command = None
                if args.checker_command:
                    try:
                        command = json.loads(args.checker_command)
                    except json.JSONDecodeError as exc:
                        raise AG2CError(f"--command must be a JSON array of strings: {exc}") from exc
                    if not isinstance(command, list):
                        raise AG2CError("--command must be a JSON array of strings")
                result = update_checker(
                    Path.cwd(),
                    checker_id=args.id,
                    actor=args.actor,
                    reason=args.reason,
                    always={"on": True, "off": False}.get(args.always) if args.always else None,
                    parse=args.parse or None,
                    timeout=args.timeout or None,
                    command=command,
                    stage=args.stage or None,
                    bind=list(args.bind),
                    budget_seconds=float(args.budget_seconds) if args.budget_seconds is not None else None,
                    implementation=args.implementation,
                )
            elif args.govern_command == "test-baseline":
                from .checks import accept_test_baseline

                result = accept_test_baseline(manifest, policy, list(args.checker), actor=args.actor, reason=args.reason)
            elif args.govern_command == "warning-dismiss":
                from .checks import dismiss_warning

                result = dismiss_warning(manifest, args.key, actor=args.actor, reason=args.reason)
            elif args.govern_command == "sandbox":
                from .sandbox import run_sandbox

                result = run_sandbox(Path.cwd(), scenario=args.scenario)
            elif args.govern_command == "trust-anchor":
                from .trust_base import write_trust_anchor

                result = write_trust_anchor(Path.cwd(), actor=args.actor, reason=args.reason)
            elif args.govern_command == "proxy":
                from .govern import configure_proxy

                result = configure_proxy(
                    Path.cwd(),
                    actor=args.actor,
                    reason=args.reason,
                    auto_settle={"on": True, "off": False}.get(args.auto_settle),
                    auto_census={"on": True, "off": False}.get(args.auto_census),
                    auto_warning={"on": True, "off": False}.get(args.auto_warning),
                    grant=bool(args.grant),
                    rule_id=str(args.rule_id or ""),
                    rule_flag=str(args.flag or ""),
                )
            elif args.govern_command == "regulator":
                from .govern import configure_regulator

                result = configure_regulator(
                    Path.cwd(),
                    actor=args.actor,
                    reason=args.reason,
                    enabled={"on": True, "off": False}.get(args.enable) if args.enable else None,
                    endpoint=args.endpoint or None,
                    model=args.model or None,
                    api_key_env=args.api_key_env or None,
                    strict={"on": True, "off": False}.get(args.strict) if args.strict else None,
                    timeout=args.timeout or None,
                    worker_model=args.worker_model or None,
                    allow_same_family={"on": True, "off": False}.get(args.allow_same_family) if args.allow_same_family else None,
                )
                if isinstance(result, dict) and result.get("warning"):
                    print(result["warning"], file=sys.stderr)
            elif args.govern_command == "trunk":
                from .govern import configure_trunk

                result = configure_trunk(Path.cwd(), branch=args.branch, actor=args.actor, reason=args.reason)
            elif args.govern_command == "hazard-dismiss":
                from .hazard import dismiss_hazard

                result = dismiss_hazard(manifest, args.target, args.kind, actor=args.actor, reason=args.reason, days=args.days)
            elif args.govern_command == "apply":
                result = apply_change(
                    Path.cwd(),
                    action=args.action,
                    kind=args.kind,
                    card_id=args.card_id,
                    reason=args.reason,
                    actor=args.actor,
                    card_type=args.card_type,
                    title=args.title,
                    summary=args.summary,
                    include=list(args.includes),
                    provides=args.provides,
                    conventions=args.conventions,
                    budget_lines=args.budget_lines,
                    optional=args.optional,
                    maturity=args.maturity,
                )
            else:
                result = retrieve_guidance(
                    Path.cwd(),
                    path_specs=list(args.paths or []),
                    contract_specs=list(args.contracts or []),
                    goal=args.goal or "",
                )
            if args.format == "json":
                print(_json(result))
            elif args.govern_command == "pending":
                items = result.get("items") or []
                if not items:
                    print("No governance updates are pending.")
                else:
                    for item in items:
                        print(f"[{item['kind']}] {item['path']} -> {item['action']}")
            elif args.govern_command == "retrieve":
                print(f"Route: {result['route']['state']}")
                print(f"Cards: {len(result['cards'])}")
                print(f"Knowledge: {len(result['knowledge'])}")
                print(f"Pending: {len(result['pending'])}")
            elif args.govern_command == "settle":
                print(f"Actor: {result['actor']}")
                print(f"Reason: {result['reason']}")
                print(f"Actions: {', '.join(result.get('actions') or []) or 'none'}")
                print(f"Remaining: {len(result.get('pending') or [])}")
            else:
                print(f"Actor: {result.get('actor', '')}")
                print(f"Reason: {result.get('reason', '')}")
                if result.get("knowledge") is not None:
                    print(f"Knowledge: {', '.join(result.get('knowledge') or []) or 'none'}")
                if result.get("id"):
                    print(f"{result['action']} {result['id']}")
            return 0
        if args.command == "coverage":
            value = coverage_view(policy, project_root=manifest.project_root)
            if args.format == "json":
                print(_json(value))
            else:
                seed = value.get("seed") or {}
                print(f"Seed: {seed.get('phase')} / sower {seed.get('sower')} / trusted {'yes' if seed.get('trusted') else 'no'}")
                print(f"Map: {value['level']}")
                print(f"Verification growth: {value['verification_growth']}")
                print(f"Detected areas: {value['area_count']}")
                print(f"Trusted checks: {value['checker_count']}")
                print(f"Public contracts: {value['contract_count']}")
                print(f"Unknown entries: {value['strategy']} expansion")
            return 0
        if args.command == "seed":
            from .seed import assess_seed, format_seed_status, run_suite, sow

            if args.seed_command == "status":
                status = assess_seed(policy, project_root=manifest.project_root)
                if args.format == "json":
                    print(_json(status))
                else:
                    print(format_seed_status(status))
                return 0
            if args.seed_command == "sow":
                result = sow(Path.cwd(), actor=args.actor, reason=args.reason)
                if args.format == "text":
                    print(format_seed_status(result["seed"]))
                    print(f"Created: {', '.join(result['created']) or 'none'}")
                else:
                    print(_json(result))
                return 0
            if args.seed_command == "run":
                return run_suite(manifest.project_root, args.suite)
            raise AG2CError("unknown seed command")
        if args.command == "index":
            path = index_path(manifest)
            if args.index_command == "build":
                published = build_index(manifest, policy, path)
                current_findings = findings(published)
                print(f"Built AG2C index: {published}")
                print(f"Findings: {len(current_findings)}")
                return 0
            if args.index_command == "verify":
                errors = verify_freshness(manifest, policy, path)
                if errors:
                    raise AG2CError("index verification failed:\n- " + "\n- ".join(errors))
                print("AG2C index is valid and current.")
                return 0
            if args.index_command == "summary":
                errors = verify_freshness(manifest, policy, path)
                if errors:
                    raise AG2CError("index is not current:\n- " + "\n- ".join(errors))
                print(_json(summary(path)))
                return 0
            errors = verify_freshness(manifest, policy, path)
            if errors:
                raise AG2CError("index is not current:\n- " + "\n- ".join(errors))
            current = findings(path)
            print(_json(current))
            return 1 if current else 0
        if args.command == "slice":
            result = _slice_from_args(args, manifest, policy)
            content = _json(result) if args.format == "json" else render_slice_markdown(result)
            _write_output(content, args.output)
            return 0
        if args.command == "check":
            entry_slice = _slice_from_args(args, manifest, policy)
            report = run_checks(
                manifest,
                policy,
                entry_slice,
                requested_checker_ids=set(args.checkers) or None,
                all_mode=bool(args.all),
            )
            if args.format == "json":
                print(_json(report))
            else:
                for result in report["results"]:
                    print(f"[{result['status']}] {result['stage']} / {result['id']} ({result['duration_ms']} ms)")
                    if result["stderr"] and result["status"] != "passed":
                        print(result["stderr"])
                print("Acceptance:")
                for stage, status in report["acceptance"].items():
                    print(f"- {stage}: {status}")
                print(f"Ledger event: {report['ledger_sequence']} / {report['ledger_event_digest']}")
            return 0 if all(result["status"] == "passed" for result in report["results"]) else 1
        if args.command == "ledger":
            if args.ledger_command == "verify":
                errors = verify_ledger(manifest.ledger_path)
                if errors:
                    raise AG2CError("ledger verification failed:\n- " + "\n- ".join(errors))
                print("AG2C ledger hash chain is valid.")
                return 0
            print(_json(ledger_summary(manifest.ledger_path)))
            return 0
        if args.command == "doctor":
            return _doctor(manifest, policy)
        if args.command == "canary":
            if args.mode == "mutation":
                from .mutation import run_mutation_canary

                result, exit_code = run_mutation_canary(manifest, policy, actor=args.actor, reason=args.reason, target=args.target)
                if args.format == "json":
                    print(_json(result))
                else:
                    if result["canary"] == "passed":
                        print(f"变异被杀（测试有牙）: {result.get('mutation', '')}")
                    elif result["canary"] == "failed":
                        print(f"变异存活（测试空心！）: {result.get('mutation', '')} 未触发任何测试失败")
                    else:
                        print(f"变异金丝雀未能执行: {result.get('reason', '')}")
                return exit_code
            return _canary(manifest, policy, actor=args.actor, reason=args.reason, output_format=args.format)
        parser.error("unhandled command")
    except (AG2CError, OSError, ValueError) as exc:
        print(f"AG2C error: {exc}", file=sys.stderr)
        return 2
    return 0
