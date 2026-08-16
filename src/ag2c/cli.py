from __future__ import annotations

import argparse
import json
import shutil
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
from .render import render_slice_markdown
from .slicer import compile_slice


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


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
        choices=("codex", "claude", "agents"),
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

    skill = subparsers.add_parser("skill", help="install or remove the packaged AG2C Skill")
    skill_commands = skill.add_subparsers(dest="skill_command", required=True)
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
    task_start.add_argument("--task-id")
    task_start.add_argument("--worktree-root", type=Path)
    task_commands.add_parser("verify")
    task_finish = task_commands.add_parser("finish")
    task_finish.add_argument("--task", required=True)
    task_finish.add_argument("--message", required=True)
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

    doctor = subparsers.add_parser("doctor", help="check configuration, activation, tools, index, and ledger")
    doctor.add_argument("--repair", action="store_true", help="restore the Skill, Git guard, activation, and index")
    doctor.add_argument("--skill-destination", type=Path)
    _add_harness_arguments(doctor)
    return parser


def _doctor(manifest, policy) -> int:
    from .enrollment import activation_status

    issues: list[str] = []
    issues.extend(activation_status(manifest.project_root)["issues"])
    for target in manifest.targets:
        if not manifest.target_root(target.target_id).is_dir():
            issues.append(f"missing target directory: {target.target_id}:{manifest.target_root(target.target_id)}")
    for checker in policy.checkers:
        if shutil.which(checker.command[0]) is None:
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
        f"{coverage['checker_count']} trusted checks / {coverage['strategy']} fallback"
    )
    if not report["tasks"]:
        print("No governed tasks have been recorded yet.")
        return
    for task in report["tasks"]:
        print(f"\n{task['goal']} [{task['id']}]")
        print(f"Management: {task['management_result']}")
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
        print(f"Evidence: {'complete' if task['evidence_complete'] else 'incomplete'}")


def main(argv: list[str] | None = None) -> int:
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
            from .harnesses import install_skills, remove_skills

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
            print(_json(stop_managing(args.path, remove_data=bool(args.remove_data))))
            return 0
        if args.command == "desktop":
            from .desktop import serve_desktop

            return serve_desktop(port=args.port, token=args.token)
        if args.command == "guard":
            from .enrollment import activation_status, guard_pre_commit

            if args.guard_command == "pre-commit":
                return guard_pre_commit(Path.cwd())
            status = activation_status(Path.cwd())
            print(_json(status))
            return 0 if status["managed"] else 1
        if args.command == "task":
            from .tasks import finish_task, start_task, task_record, verify_task

            if args.task_command == "start":
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
                        )
                    )
                )
                return 0
            if args.task_command == "verify":
                result = verify_task(Path.cwd())
                print(_json(result))
                return 0 if result["passed"] else 1
            if args.task_command == "finish":
                print(_json(finish_task(Path.cwd(), args.task, message=args.message)))
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
            evidence_ok = all(task["management_result"] == "successful" for task in report["tasks"])
            return 0 if report["managed"] and report["ledger_valid"] and evidence_ok else 1
        if args.command == "doctor" and args.repair:
            from .enrollment import repair_project

            repair_project(
                Path.cwd(),
                skill_root=args.skill_destination,
                harnesses=tuple(args.harnesses) if args.harnesses else None,
            )
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
        manifest, policy = _loaded(args)
        if args.command == "coverage":
            value = {
                "level": policy.coverage.level,
                "strategy": policy.coverage.strategy,
                "managed_by": policy.coverage.managed_by,
                "areas": list(policy.coverage.areas),
                "area_count": len([card for card in policy.cards if card.card_type == "floor"]),
                "checker_count": len(policy.checkers),
                "contract_count": len(policy.contracts),
            }
            if args.format == "json":
                print(_json(value))
            else:
                print(f"Coverage level: {value['level']}")
                print(f"Detected areas: {value['area_count']}")
                print(f"Trusted checks: {value['checker_count']}")
                print(f"Public contracts: {value['contract_count']}")
                print(f"Unknown entries: {value['strategy']} expansion")
            return 0
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
        parser.error("unhandled command")
    except (AG2CError, OSError, ValueError) as exc:
        print(f"AG2C error: {exc}", file=sys.stderr)
        return 2
    return 0
