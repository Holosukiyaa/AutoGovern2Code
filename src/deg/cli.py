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
from .errors import DEGError
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
    manifest = load_manifest(manifest_path)
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="deg", description="Deterministic Engineering Governance")
    parser.add_argument("--version", action="version", version=f"DEG {__version__}")
    parser.add_argument("--manifest", type=Path, help="path to .deg/manifest.json")
    subparsers = parser.add_subparsers(dest="command", required=True)

    enroll = subparsers.add_parser("enroll", help="enroll a clean Git project in automatic DEG governance")
    enroll.add_argument("path", type=Path, nargs="?", default=Path.cwd())
    enroll.add_argument("--project-id")

    activate = subparsers.add_parser("activate", help="restore the local Skill and Git guard after cloning")
    activate.add_argument("path", type=Path, nargs="?", default=Path.cwd())

    skill = subparsers.add_parser("skill", help="install the packaged DEG Skill")
    skill_commands = skill.add_subparsers(dest="skill_command", required=True)
    skill_install = skill_commands.add_parser("install")
    skill_install.add_argument("--destination", type=Path, help="skills directory; defaults to CODEX_HOME/skills")

    guard = subparsers.add_parser("guard", help="internal activation and Git enforcement")
    guard_commands = guard.add_subparsers(dest="guard_command", required=True)
    guard_commands.add_parser("status")
    guard_commands.add_parser("pre-commit")

    task = subparsers.add_parser("task", help="internal lifecycle used by the DEG Skill")
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

    evidence = subparsers.add_parser("evidence", help="show read-only proof of DEG management")
    evidence.add_argument("--task")
    evidence.add_argument("--format", choices=("text", "json"), default="text")

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

    subparsers.add_parser("doctor", help="check configuration, tools, index, and ledger")
    return parser


def _doctor(manifest, policy) -> int:
    issues: list[str] = []
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
        print("DEG doctor found issues:")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print("DEG configuration, tools, index, and ledger are current.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "enroll":
            from .enrollment import enroll_project

            print(_json(enroll_project(args.path, project_id=args.project_id)))
            return 0
        if args.command == "activate":
            from .enrollment import activate_project

            print(_json(activate_project(args.path)))
            return 0
        if args.command == "skill":
            from .enrollment import install_skill

            print(f"Installed DEG Skill: {install_skill(args.destination)}")
            return 0
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
                print(f"DEG evidence for {report['project']}")
                print(f"Management active: {'yes' if report['managed'] else 'no'}")
                print(f"Ledger valid: {'yes' if report['ledger_valid'] else 'no'}")
                for task in report["tasks"]:
                    print(f"\n[{task['state']}] {task['id']} - {task['goal']}")
                    print(f"- managed from start: {'yes' if task['managed'] else 'no'}")
                    print(f"- management result: {task['management_result']}")
                    print(f"- evidence complete: {'yes' if task['evidence_complete'] else 'no'}")
                    print(f"- route: {task['route_state']}")
                    if task["interventions"]:
                        print("- interventions:")
                        for intervention in task["interventions"]:
                            detail = {key: value for key, value in intervention.items() if key not in {"kind", "occurred_at", "ledger_event_digest"}}
                            print(f"  - {intervention['kind']}: {json.dumps(detail, ensure_ascii=False, sort_keys=True)}")
                    else:
                        print("- interventions: none")
                    print(f"- verification attempts: {task['verification_attempts']}")
                    for verification in task["verifications"]:
                        failed = [item["id"] for item in verification["checker_results"] if item["status"] != "passed"]
                        result = "passed" if verification["passed"] else "failed"
                        suffix = f"; failed: {', '.join(failed)}" if failed else ""
                        print(f"  - attempt {verification['attempt']}: {result}{suffix}")
                    print(f"- final verification: {'passed' if task['verified'] else 'not passed'}")
                    if task["result"]:
                        print(f"- merged commit: {task['result']['commit']}")
            evidence_ok = all(task["management_result"] == "successful" for task in report["tasks"])
            return 0 if report["managed"] and report["ledger_valid"] and evidence_ok else 1
        manifest, policy = _loaded(args)
        if args.command == "index":
            path = index_path(manifest)
            if args.index_command == "build":
                published = build_index(manifest, policy, path)
                current_findings = findings(published)
                print(f"Built DEG index: {published}")
                print(f"Findings: {len(current_findings)}")
                return 0
            if args.index_command == "verify":
                errors = verify_freshness(manifest, policy, path)
                if errors:
                    raise DEGError("index verification failed:\n- " + "\n- ".join(errors))
                print("DEG index is valid and current.")
                return 0
            if args.index_command == "summary":
                errors = verify_freshness(manifest, policy, path)
                if errors:
                    raise DEGError("index is not current:\n- " + "\n- ".join(errors))
                print(_json(summary(path)))
                return 0
            errors = verify_freshness(manifest, policy, path)
            if errors:
                raise DEGError("index is not current:\n- " + "\n- ".join(errors))
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
                    raise DEGError("ledger verification failed:\n- " + "\n- ".join(errors))
                print("DEG ledger hash chain is valid.")
                return 0
            print(_json(ledger_summary(manifest.ledger_path)))
            return 0
        if args.command == "doctor":
            return _doctor(manifest, policy)
        parser.error("unhandled command")
    except (DEGError, OSError, ValueError) as exc:
        print(f"DEG error: {exc}", file=sys.stderr)
        return 2
    return 0
