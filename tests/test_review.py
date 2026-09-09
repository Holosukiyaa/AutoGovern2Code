"""Tests for the AI regulator (agent-review): prompt isolation, verdict
validation, and the degrade paths. All LLM calls are mocked — no network."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bootstrap  # noqa: F401

from ag2c.config import load_manifest, load_policy
from ag2c.model import RegulatorConfig
from ag2c.review import (
    RegulatorError,
    build_messages,
    parse_verdict,
    run_agent_review,
    verdict_problems,
)


from support import _git


def _governed_repo(root: Path, *, regulator: dict | None = None):
    """Minimal governed git project: one floor, one always-passing checker."""
    (root / ".ag2c" / "state").mkdir(parents=True)
    (root / "src").mkdir()
    (root / "src" / "value.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.name", "AG2C Test")
    _git(root, "config", "user.email", "ag2c-test@example.invalid")
    manifest = {
        "schema": "ag2c.manifest.v1",
        "project": {"id": "review-project"},
        "policy": ".ag2c/policy.json",
        "state_dir": ".ag2c/state",
        "ledger": ".ag2c/ledger.jsonl",
        "targets": [{"id": "app", "path": ".", "governed_roots": ["src"], "exclude": []}],
    }
    policy = {
        "schema": "ag2c.policy.v1",
        "cards": [
            {"id": "constitution.project", "type": "constitution", "title": "C", "summary": "S"},
            {
                "id": "floor.src",
                "type": "floor",
                "title": "Src",
                "summary": "Owns src.",
                "scopes": [{"target": "app", "include": ["src/**"], "ownership": "primary"}],
                "checkers": ["check.noop"],
            },
        ],
        "relations": [],
        "contracts": [],
        "checkers": [
            {
                "id": "check.noop",
                "stage": "floor",
                "target": "app",
                "command": [sys.executable, "-c", "print('noop')"],
                "cwd": ".",
                "timeout": 30,
            }
        ],
    }
    if regulator is not None:
        policy["regulator"] = regulator
    (root / ".ag2c" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / ".ag2c" / "policy.json").write_text(json.dumps(policy), encoding="utf-8")
    _git(root, "add", "--all")
    _git(root, "commit", "-m", "initial")
    loaded = load_manifest(root / ".ag2c" / "manifest.json")
    return loaded, load_policy(loaded)


def _task(root: Path) -> dict:
    return {
        "id": "t-review",
        "source": {"head": _git(root, "rev-parse", "HEAD")},
        "portrait": "Done looks like: value.py 提供 RETRY 常量。Surfaces: 单测断言。",
    }


def _report() -> dict:
    return {
        "results": [{"id": "check.noop", "stage": "floor", "status": "passed", "exit_code": 0}],
        "acceptance": "ok",
    }


def _verdict(outcome: str, items: list[dict]) -> str:
    return json.dumps({"verdict": outcome, "items": items, "summary": "总评"}, ensure_ascii=False)


class PromptTests(unittest.TestCase):
    def test_messages_carry_exactly_the_three_evidences(self) -> None:
        messages = build_messages("画像内容", "diff 内容", "机器报告内容")
        self.assertEqual(2, len(messages))
        system, user = messages[0]["content"], messages[1]["content"]
        # 对抗性框架 + 信息隔离写死在系统提示词里
        self.assertIn("找出这次交付失败的方式", system)
        self.assertIn("看不到施工者", system)
        self.assertIn("file:line", system)
        # 三样物证都在；别的东西不在
        self.assertIn("画像内容", user)
        self.assertIn("diff 内容", user)
        self.assertIn("机器报告内容", user)


class ParseTests(unittest.TestCase):
    def test_plain_json(self) -> None:
        self.assertEqual({"verdict": "pass"}, parse_verdict('{"verdict": "pass"}'))

    def test_fenced_json(self) -> None:
        self.assertEqual({"verdict": "pass"}, parse_verdict('```json\n{"verdict": "pass"}\n```'))

    def test_non_json_rejected(self) -> None:
        with self.assertRaises(RegulatorError):
            parse_verdict("我觉得这次交付挺不错的")


class VerdictValidationTests(unittest.TestCase):
    def test_valid_pass(self) -> None:
        verdict = {"verdict": "pass", "items": [{"name": "承诺兑现", "status": "pass", "evidence": "", "comment": "兑现了"}]}
        self.assertEqual([], verdict_problems(verdict))

    def test_fail_without_evidence_is_voided(self) -> None:
        verdict = {
            "verdict": "reject",
            "items": [{"name": "复用", "status": "fail", "evidence": "", "comment": "复用率不高"}],
        }
        problems = verdict_problems(verdict)
        self.assertTrue(any("file:line" in problem for problem in problems), problems)

    def test_fail_with_evidence_passes(self) -> None:
        verdict = {
            "verdict": "reject",
            "items": [{"name": "复用", "status": "fail", "evidence": "tasks.py:347", "comment": "重复实现"}],
        }
        self.assertEqual([], verdict_problems(verdict))

    def test_reject_requires_a_fail_item(self) -> None:
        verdict = {"verdict": "reject", "items": [{"name": "x", "status": "pass", "evidence": "", "comment": "好"}]}
        self.assertTrue(verdict_problems(verdict))

    def test_pass_forbids_fail_items(self) -> None:
        verdict = {
            "verdict": "pass",
            "items": [{"name": "x", "status": "fail", "evidence": "a.py:1", "comment": "坏"}],
        }
        self.assertTrue(verdict_problems(verdict))

    def test_empty_comment_rejected(self) -> None:
        verdict = {"verdict": "pass", "items": [{"name": "x", "status": "pass", "evidence": "", "comment": "  "}]}
        self.assertTrue(verdict_problems(verdict))


class RunAgentReviewTests(unittest.TestCase):
    def test_not_configured_degrades_with_gap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, policy = _governed_repo(root)
            result = run_agent_review(root, _task(root), policy, _report())
            self.assertEqual("unavailable", result["outcome"])
            self.assertEqual("not-configured", result["reason"])
            self.assertIn("本次缺 AI 监管", result["gap"])

    def test_disabled_degrades(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, policy = _governed_repo(root, regulator={"enabled": False})
            result = run_agent_review(root, _task(root), policy, _report())
            self.assertEqual("unavailable", result["outcome"])

    def test_pass_verdict_and_diff_reaches_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, policy = _governed_repo(root, regulator={"enabled": True, "endpoint": "http://127.0.0.1:9/v1", "model": "mock"})
            (root / "src" / "value.py").write_text("VALUE = 1\nRETRY = 3\n", encoding="utf-8")
            good = _verdict("pass", [{"name": "承诺兑现", "status": "pass", "evidence": "", "comment": "RETRY 已加"}])
            with patch("ag2c.review.call_chat", return_value=good) as mocked:
                result = run_agent_review(root, _task(root), policy, _report())
            self.assertEqual("passed", result["outcome"])
            self.assertEqual("pass", result["verdict"]["verdict"])
            # 信息流的端到端：diff 真进了提示词，画像也进了
            messages = mocked.call_args[0][1]
            self.assertIn("RETRY = 3", messages[1]["content"])
            self.assertIn("RETRY 常量", messages[1]["content"])

    def test_reject_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, policy = _governed_repo(root, regulator={"enabled": True, "endpoint": "http://127.0.0.1:9/v1", "model": "mock"})
            (root / "src" / "value.py").write_text("VALUE = 2\n", encoding="utf-8")
            bad = _verdict("reject", [{"name": "逻辑", "status": "fail", "evidence": "src/value.py:1", "comment": "擅自改值"}])
            with patch("ag2c.review.call_chat", return_value=bad):
                result = run_agent_review(root, _task(root), policy, _report())
            self.assertEqual("rejected", result["outcome"])

    def test_fail_without_evidence_voids_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, policy = _governed_repo(root, regulator={"enabled": True, "endpoint": "http://127.0.0.1:9/v1", "model": "mock"})
            (root / "src" / "value.py").write_text("VALUE = 2\n", encoding="utf-8")
            bad = _verdict("reject", [{"name": "复用", "status": "fail", "evidence": "", "comment": "复用率不高"}])
            with patch("ag2c.review.call_chat", return_value=bad):
                result = run_agent_review(root, _task(root), policy, _report())
            self.assertEqual("unavailable", result["outcome"])
            self.assertIn("invalid-verdict", result["reason"])
            self.assertIn("裁决作废", result["gap"])

    def test_call_failure_degrades(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, policy = _governed_repo(root, regulator={"enabled": True, "endpoint": "http://127.0.0.1:9/v1", "model": "mock"})
            with patch("ag2c.review.call_chat", side_effect=RegulatorError("connection refused")):
                result = run_agent_review(root, _task(root), policy, _report())
            self.assertEqual("unavailable", result["outcome"])
            self.assertIn("connection refused", result["reason"])


class PolicyParsingTests(unittest.TestCase):
    def test_enabled_requires_endpoint_and_model(self) -> None:
        from ag2c.errors import ConfigurationError

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ConfigurationError):
                _governed_repo(root, regulator={"enabled": True})

    def test_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, policy = _governed_repo(root, regulator={"enabled": False})
            config = policy.regulator
            self.assertIsNotNone(config)
            self.assertFalse(config.strict)
            self.assertEqual("AG2C_REGULATOR_API_KEY", config.api_key_env)
            self.assertEqual(180, config.timeout)


if __name__ == "__main__":
    unittest.main()
