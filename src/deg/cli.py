from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .checks import run_checks
from .config import MANIFEST_SCHEMA, POLICY_SCHEMA, discover_manifest, load_manifest, load_policy
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


def _project_id(path: Path) -> str:
    value = re.sub(r"[^a-z0-9._-]+", "-", path.name.lower()).strip("-.")
    return value or "project"


def _init_project(root: Path, project_id: str | None, force: bool) -> int:
    root = root.resolve()
    config_dir = root / ".deg"
    manifest_path = config_dir / "manifest.json"
    policy_path = config_dir / "policy.json"
    guide_path = config_dir / "README.md"
    existing = [path for path in (manifest_path, policy_path, guide_path) if path.exists()]
    if existing and not force:
        raise DEGError("refusing to overwrite existing DEG files: " + ", ".join(str(path) for path in existing))
    config_dir.mkdir(parents=True, exist_ok=True)
    project_id = project_id or _project_id(root)
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", project_id):
        raise DEGError("project id must contain only lowercase letters, digits, dots, underscores, and hyphens")
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "project": {"id": project_id},
        "policy": ".deg/policy.json",
        "state_dir": ".deg/state",
        "ledger": ".deg/ledger.jsonl",
        "targets": [
            {
                "id": "app",
                "path": ".",
                "governed_roots": ["src"],
                "exclude": ["src/**/__pycache__/**"],
            }
        ],
    }
    policy = {
        "schema": POLICY_SCHEMA,
        "cards": [
            {
                "id": "constitution.project",
                "type": "constitution",
                "title": "Project governance",
                "summary": "Global rules that every governed change must preserve.",
                "references": ["README.md"],
            },
            {
                "id": "floor.app",
                "type": "floor",
                "title": "Application",
                "summary": "Primary ownership for application source code.",
                "scopes": [{"target": "app", "include": ["src/**"], "ownership": "primary"}],
                "checkers": ["check.git-diff"],
                "references": ["README.md"],
            },
            {
                "id": "knowledge.app",
                "type": "knowledge",
                "title": "Application navigation",
                "summary": "Current implementation notes for contributors entering application code.",
                "scopes": [{"target": "app", "include": ["src/**"], "ownership": "reference"}],
                "references": ["README.md"],
            },
        ],
        "relations": [{"source": "knowledge.app", "type": "explains", "target": "floor.app"}],
        "contracts": [],
        "checkers": [
            {
                "id": "check.git-diff",
                "stage": "floor",
                "target": "app",
                "command": ["git", "diff", "--check"],
                "cwd": ".",
                "timeout": 60,
            }
        ],
    }
    guide = """# Project DEG configuration

Start with an exact entry, not a broad goal:

```text
deg index build
deg slice --path app:src/path/to/file.py --output .deg/state/slice.md
deg check --path app:src/path/to/file.py
```

Edit `manifest.json` to declare repositories and governed roots. Edit `policy.json`
to declare ownership Floors, local Knowledge, Boundaries, public contract bindings,
and real project checkers. Replace the generated `git diff --check` checker with the
project's native tests and build commands.

Read the Entry Slicing guide before adding broad scopes:
https://github.com/Holosukiyaa/DEG/blob/main/docs/ENTRY_SLICING.md
"""
    manifest_path.write_text(_json(manifest) + "\n", encoding="utf-8")
    policy_path.write_text(_json(policy) + "\n", encoding="utf-8")
    guide_path.write_text(guide, encoding="utf-8")
    print(f"Initialized DEG in {config_dir}")
    print("Next: review .deg/policy.json, then run `deg index build`.")
    return 0


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


def _add_slice_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--path", dest="paths", action="append", default=[], help="target-id:relative/path")
    parser.add_argument("--contract", dest="contracts", action="append", default=[], help="target-id:contract-id@version")
    parser.add_argument("--goal", default="", help="advisory task description; never selects ownership by itself")
    parser.add_argument("--all", action="store_true", help="select all policy areas and checkers")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="deg", description="Deterministic Engineering Governance")
    parser.add_argument("--version", action="version", version=f"DEG {__version__}")
    parser.add_argument("--manifest", type=Path, help="path to .deg/manifest.json")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="create a starter DEG policy")
    init.add_argument("path", type=Path, nargs="?", default=Path.cwd())
    init.add_argument("--project-id")
    init.add_argument("--force", action="store_true")

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
        if args.command == "init":
            return _init_project(args.path, args.project_id, args.force)
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
