from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import bootstrap

from ag2c import __version__, tasks
from ag2c.cli_main import main
from ag2c.tasks import _orient_next
from ag2c.errors import AG2CError


class CLITests(unittest.TestCase):
    def test_browser_viewer_command_is_removed(self) -> None:
        output = io.StringIO()
        with patch("ag2c_gui.desktop.serve_desktop") as serve, redirect_stdout(output):
            with self.assertRaises(SystemExit):
                main(["viewer", "--open"])
        serve.assert_not_called()

    def test_project_uninstall_removes_governance_data(self) -> None:
        output = io.StringIO()
        with patch("ag2c.management.stop_managing", return_value={"uninstalled": True, "data_removed": True}) as stop, redirect_stdout(output):
            self.assertEqual(0, main(["project", "uninstall", "C:/tmp/project"]))
        stop.assert_called_once()
        self.assertTrue(stop.call_args.kwargs["remove_data"])

    def test_skill_prompt_prints_plain_entry_text(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(0, main(["skill", "prompt", "--project", "."]))
        text = output.getvalue()
        for needle in ("ag2c skill install", "ag2c skill version", "ag2c guard status", "ag2c-directory-census", "ag2c-knowledge-authoring", f"version {__version__}", "replace the installed copy if missing or different"):
            self.assertIn(needle, text)
        self.assertNotIn("docs/skills", text)

    def test_skill_version_prints_packaged_identity(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(0, main(["skill", "version"]))
        payload = json.loads(output.getvalue())
        self.assertEqual(__version__, payload["package"])
        self.assertEqual(["ag2c-governed-development", "ag2c-governance-update", "ag2c-directory-census", "ag2c-knowledge-authoring", "ag2c-full-liquidation"], [item["name"] for item in payload["skills"]])
        self.assertTrue(all(item["version"] == __version__ and item["digest"] for item in payload["skills"]))


class GovernCheckerParserTests(unittest.TestCase):
    def test_checker_command_flag_does_not_clobber_the_subcommand(self) -> None:
        from ag2c.cli import build_parser

        args = build_parser().parse_args(["govern", "checker", "--id", "check.suite-x", "--command", '["python","-B","tests/suites.py","x"]', "--bind", "knowledge.room", "--actor", "a", "--reason", "r"])
        self.assertEqual("govern", args.command)
        self.assertEqual("checker", args.govern_command)
        self.assertEqual('["python","-B","tests/suites.py","x"]', args.checker_command)
        self.assertEqual(["knowledge.room"], args.bind)

    def test_govern_checker_parallelism_parses(self) -> None:
        from ag2c.cli import build_parser

        args = build_parser().parse_args(["govern", "checker-parallelism", "--workers", "4", "--actor", "a", "--reason", "r"])
        self.assertEqual("govern", args.command)
        self.assertEqual("checker-parallelism", args.govern_command)
        self.assertEqual(4, args.workers)

    def test_cost_report_and_finish_self_report_parse(self) -> None:
        from ag2c.cli import build_parser
        cost = build_parser().parse_args(["govern", "cost-report", "--format", "json"])
        self.assertEqual("cost-report", cost.govern_command)
        finish = build_parser().parse_args(["task", "finish", "--task", "t", "--message", "m", "--proof", "p", "--sessions", "2", "--estimated-tokens", '{"model":"grok","input":1,"output":2}'])
        self.assertEqual(2, finish.sessions)
        self.assertIn("grok", finish.estimated_tokens)


class StdioEncodingTests(unittest.TestCase):
    def test_json_keeps_chinese_reason(self) -> None:
        from ag2c.cli import _json
        blob = _json({"reason": "首次演习"})
        self.assertIn("首次演习", blob)
        self.assertNotIn("\\u9996", blob)

    def test_windows_stdio_sets_utf8_console_cp(self) -> None:
        import ctypes
        from ag2c.cli import _configure_stdio
        calls: list = []
        kernel32 = type("K", (), {"SetConsoleOutputCP": lambda self, cp: calls.append(("out", cp)), "SetConsoleCP": lambda self, cp: calls.append(("in", cp))})()
        with patch("ag2c.cli.sys.platform", "win32"), patch.object(ctypes, "windll", type("W", (), {"kernel32": kernel32})(), create=True):
            _configure_stdio()
        self.assertEqual([("out", 65001), ("in", 65001)], calls)

    def test_non_windows_skips_kernel32(self) -> None:
        import ctypes
        from ag2c.cli import _configure_stdio
        calls: list = []
        kernel32 = type("K", (), {"SetConsoleOutputCP": lambda self, cp: calls.append(("out", cp)), "SetConsoleCP": lambda self, cp: calls.append(("in", cp))})()
        with patch("ag2c.cli.sys.platform", "linux"), patch.object(ctypes, "windll", type("W", (), {"kernel32": kernel32})(), create=True):
            _configure_stdio()
        self.assertEqual([], calls)


class ResultGateCliTests(unittest.TestCase):
    def test_task_start_requires_the_portrait(self) -> None:
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(["task", "start", "--goal", "g", "--path", "app:a.py"])

    def test_task_finish_requires_proof(self) -> None:
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(["task", "finish", "--task", "t", "--message", "m"])

    def test_default_portrait_derives_from_the_goal(self) -> None:
        self.assertIn("修 bug", tasks._default_portrait("修 bug"))


class WorktreeLocationTests(unittest.TestCase):
    def test_outside_worktree_needs_no_ignore_rule(self) -> None:
        with patch("ag2c.tasks.git") as runner:
            tasks._ensure_worktree_location(Path("C:/repo"), Path("D:/ag2c-worktrees/task-1"))
        runner.assert_not_called()

    def test_in_checkout_worktree_allowed_when_git_ignores_it(self) -> None:
        worktree = Path("C:/repo/data/projects/key/worktrees/task-1")
        with patch("ag2c.tasks.git", return_value="data/projects/key/worktrees/task-1\n") as runner:
            tasks._ensure_worktree_location(Path("C:/repo"), worktree)
        runner.assert_called_once()
        self.assertEqual("check-ignore", runner.call_args.args[1])

    def test_in_checkout_worktree_refused_when_not_ignored(self) -> None:
        with patch("ag2c.tasks.git", return_value=""):
            with self.assertRaises(AG2CError):
                tasks._ensure_worktree_location(Path("C:/repo"), Path("C:/repo/src/worktrees/task-1"))


class OrientNextTests(unittest.TestCase):
    def _next(self, lifecycle: str, **overrides):
        options = {
            "has_changes": False,
            "canonical_dirty": False,
            "pending_count": 0,
            "task_id": "task-1",
            "worktree_path": "C:/worktrees/task-1",
        }
        options.update(overrides)
        return _orient_next(lifecycle, **options)

    def test_missing_points_to_abandon(self) -> None:
        action = self._next("missing")
        self.assertEqual("ag2c_task_abandon", action["tool"])
        self.assertEqual("task-1", action["args"]["task"])

    def test_diverged_points_to_refresh(self) -> None:
        action = self._next("diverged")
        self.assertEqual("ag2c_task_refresh", action["tool"])
        self.assertEqual("task-1", action["args"]["task"])

    def test_verified_stale_reverifies_from_the_worktree(self) -> None:
        action = self._next("verified-stale")
        self.assertEqual("ag2c_task_verify", action["tool"])
        self.assertEqual("C:/worktrees/task-1", action["args"]["cwd"])

    def test_verified_unmerged_points_to_finish(self) -> None:
        action = self._next("verified-unmerged")
        self.assertEqual("ag2c_task_finish", action["tool"])
        self.assertEqual("task-1", action["args"]["task"])
        self.assertNotIn("dirty", action["note"])

    def test_verified_unmerged_warns_when_canonical_dirty(self) -> None:
        action = self._next("verified-unmerged", canonical_dirty=True)
        self.assertIn("dirty", action["note"])

    def test_completed_with_pending_items_points_to_settle(self) -> None:
        action = self._next("completed", pending_count=2)
        self.assertEqual("ag2c_settle", action["tool"])
        self.assertIn("2", action["note"])

    def test_completed_without_pending_items_is_done(self) -> None:
        action = self._next("completed")
        self.assertIsNone(action["tool"])

    def test_abandoned_is_terminal(self) -> None:
        action = self._next("abandoned")
        self.assertIsNone(action["tool"])

    def test_in_progress_without_changes_waits_for_edits(self) -> None:
        action = self._next("in-progress")
        self.assertIsNone(action["tool"])
        self.assertIn("C:/worktrees/task-1", action["note"])

    def test_in_progress_with_changes_verifies(self) -> None:
        action = self._next("in-progress", has_changes=True)
        self.assertEqual("ag2c_task_verify", action["tool"])
        self.assertEqual("C:/worktrees/task-1", action["args"]["cwd"])

    def test_evidence_coverage_line_names_verification_growth(self) -> None:
        from ag2c.cli import _print_evidence

        output = io.StringIO()
        report = {
            "project": "demo",
            "managed": True,
            "ledger_valid": True,
            "coverage": {
                "level": "structured",
                "area_count": 2,
                "checker_count": 3,
                "strategy": "conservative",
                "verification_growth": "unsplit",
                "seed": {
                    "phase": "mapped",
                    "sower": "none",
                    "trusted": False,
                    "summary": "rooms/cards exist; product tests are still one blob",
                },
            },
            "tasks": [],
        }
        with redirect_stdout(output):
            _print_evidence(report)
        text = output.getvalue()
        self.assertIn("Seed: mapped / sower none / trusted no", text)
        self.assertIn("Map: structured / 2 areas / 3 trusted checks / conservative fallback / verification unsplit", text)
        self.assertNotIn("Coverage: structured", text)
        self.assertIn("No governed tasks have been recorded yet.", text)
