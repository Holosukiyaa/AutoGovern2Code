from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bootstrap  # noqa: F401

from ag2c.harnesses import PACKAGED_SKILLS
from ag2c.mcp_server import (
    CONNECT_RESOURCE_URI,
    MCP_INSTRUCTIONS,
    PYTHON_PLACEHOLDER,
    SRC_PLACEHOLDER,
    handle_mcp_request,
    install_mcp_clients,
    mcp_config_snippet,
    mcp_connect_prompt,
    mcp_health,
    mcp_stdio_command,
    mcp_toml_block,
    serve_mcp_stdio,
    tool_defs,
)


def _rpc(method: str, params: dict | None = None, req_id: int = 1) -> dict:
    message = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        message["params"] = params
    reply = handle_mcp_request(message)
    assert reply is not None
    return reply


class McpServerTests(unittest.TestCase):
    def test_initialize_embeds_skill_workflow(self) -> None:
        reply = _rpc(
            "initialize",
            {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}},
        )
        result = reply["result"]
        self.assertEqual("2025-03-26", result["protocolVersion"])
        self.assertIn("tools", result["capabilities"])
        self.assertIn("resources", result["capabilities"])
        self.assertIn("ag2c_task_start", result["instructions"])
        self.assertIn("guidance.lineage", result["instructions"])
        self.assertIn("Do not ask the user to paste a copy-prompt", result["instructions"])
        self.assertIn(MCP_INSTRUCTIONS.strip()[:40], result["instructions"])
        # Hard rules learned in production must ship in the auto-injected instructions.
        self.assertIn("census-stale", result["instructions"])
        self.assertIn("20 characters max", result["instructions"])
        self.assertIn("runs in the background", result["instructions"])
        self.assertIn("zero-regression", result["instructions"])
        self.assertIn("canonical checkout", result["instructions"])

    def test_census_tool_schema_exposes_record_all(self) -> None:
        census = next(item for item in tool_defs() if item["name"] == "ag2c_census")
        properties = census["inputSchema"]["properties"]
        self.assertIn("record", properties)
        self.assertIn("all", properties)
        self.assertEqual("boolean", properties["all"]["type"])

    def test_household_tool_schema_exposes_entrypoint_checker_command(self) -> None:
        household = next(item for item in tool_defs() if item["name"] == "ag2c_household")
        properties = household["inputSchema"]["properties"]
        for key in ("entrypoint", "checker", "command"):
            self.assertIn(key, properties)
            self.assertEqual("array", properties[key]["type"])

    def test_tighten_tool_schema_and_dispatch(self) -> None:
        tighten = next(item for item in tool_defs() if item["name"] == "ag2c_tighten")
        schema = tighten["inputSchema"]
        self.assertEqual(["id", "reason"], schema["required"])
        self.assertIn("renew", schema["properties"])
        with tempfile.TemporaryDirectory() as tmp:
            response = handle_mcp_request(
                {
                    "jsonrpc": "2.0",
                    "id": 9,
                    "method": "tools/call",
                    "params": {"name": "ag2c_tighten", "arguments": {"cwd": tmp, "id": "knowledge.x", "reason": "probe"}},
                }
            )
        self.assertTrue(response["result"]["isError"])

    def test_tools_list_covers_the_skill_routes(self) -> None:
        names = {item["name"] for item in tool_defs()}
        self.assertTrue(
            {
                "ag2c_guard_status",
                "ag2c_task_start",
                "ag2c_task_verify",
                "ag2c_task_finish",
                "ag2c_task_orient",
                "ag2c_census",
                "ag2c_span",
                "ag2c_household",
                "ag2c_tighten",
                "ag2c_apply",
                "ag2c_skill",
                "ag2c_mcp_health",
            }.issubset(names)
        )
        listed = _rpc("tools/list")["result"]["tools"]
        self.assertEqual(names, {item["name"] for item in listed})

    def test_orient_dispatch_reaches_the_engine(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            response = handle_mcp_request(
                {
                    "jsonrpc": "2.0",
                    "id": 7,
                    "method": "tools/call",
                    "params": {"name": "ag2c_task_orient", "arguments": {"cwd": tmp}},
                }
            )
        # Outside a registered repo the engine refuses; the wire still gets a
        # structured isError result instead of a crashed stdio loop.
        self.assertTrue(response["result"]["isError"])

    def test_resources_expose_packaged_skills(self) -> None:
        resources = _rpc("resources/list")["result"]["resources"]
        uris = {item["uri"] for item in resources}
        self.assertIn(CONNECT_RESOURCE_URI, uris)
        for name in PACKAGED_SKILLS:
            self.assertIn(f"ag2c://skill/{name}", uris)
        body = _rpc("resources/read", {"uri": "ag2c://skill/ag2c-governed-development"})["result"]
        text = body["contents"][0]["text"]
        self.assertIn("ag2c-governed-development", text)
        self.assertIn("task start", text.casefold() or text)
        skill = _rpc("tools/call", {"name": "ag2c_skill", "arguments": {"name": "ag2c-directory-census"}})
        payload = json.loads(skill["result"]["content"][0]["text"])
        self.assertIn("未打标", payload["text"])

    def test_unknown_tool_is_tool_error_not_crash(self) -> None:
        reply = _rpc("tools/call", {"name": "nope", "arguments": {}})
        self.assertTrue(reply["result"]["isError"])
        self.assertIn("unknown tool", reply["result"]["content"][0]["text"])

    def test_stdio_roundtrip_initialize(self) -> None:
        inbound = io.StringIO(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 7,
                    "method": "initialize",
                    "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}},
                }
            )
            + "\n"
        )
        outbound = io.StringIO()
        serve_mcp_stdio(stdin=inbound, stdout=outbound)
        lines = [line for line in outbound.getvalue().splitlines() if line.strip()]
        self.assertEqual(1, len(lines))
        payload = json.loads(lines[0])
        self.assertEqual(7, payload["id"])
        self.assertIn("instructions", payload["result"])

    def test_stdio_reconfigures_locale_stdin_to_utf8(self) -> None:
        message = {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {"name": "未知工具", "arguments": {}},
        }
        raw = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
        locale_stdin = io.TextIOWrapper(io.BytesIO(raw), encoding="gbk", errors="surrogateescape")
        outbound = io.StringIO()
        with patch("sys.stdin", locale_stdin):
            serve_mcp_stdio(stdout=outbound)
        lines = [line for line in outbound.getvalue().splitlines() if line.strip()]
        self.assertEqual(1, len(lines))
        payload = json.loads(lines[0])
        self.assertIn("未知工具", payload["result"]["content"][0]["text"])

    def test_install_writes_grok_and_cursor_configs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            written = install_mcp_clients(home=home)
            harnesses = {item["harness"] for item in written}
            self.assertIn("grok", harnesses)
            self.assertIn("cursor", harnesses)
            toml = (home / ".grok" / "config.toml").read_text(encoding="utf-8")
            self.assertIn("[mcp_servers.ag2c]", toml)
            self.assertIn("-m", toml)
            self.assertIn("ag2c", toml)
            self.assertIn("PYTHONPATH", toml)
            cursor = json.loads((home / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
            self.assertEqual(mcp_stdio_command()[0], cursor["mcpServers"]["ag2c"]["command"])
            self.assertIn("PYTHONPATH", cursor["mcpServers"]["ag2c"].get("env") or {})
            install_mcp_clients(home=home)
            again = (home / ".grok" / "config.toml").read_text(encoding="utf-8")
            self.assertEqual(1, again.count("[mcp_servers.ag2c]"))

    def test_mcp_command_does_not_use_pythonw(self) -> None:
        command = mcp_stdio_command()
        self.assertNotIn("pythonw", command[0].lower())
        self.assertIn("mcp", command)

    def test_connect_prompt_uses_placeholders_not_vendors_or_paths(self) -> None:
        prompt = mcp_connect_prompt()
        self.assertIn(PYTHON_PLACEHOLDER, prompt)
        self.assertIn(SRC_PLACEHOLDER, prompt)
        self.assertIn("stdio", prompt.casefold())
        lowered = prompt.casefold()
        for vendor in ("grok", "cursor", "claude", "codex"):
            self.assertNotIn(vendor, lowered)
        self.assertNotIn(str(Path.home()), prompt)
        self.assertNotIn("C:\\Users\\", prompt)
        self.assertNotIn("/Users/", prompt)
        snippet = mcp_config_snippet(placeholders=True)
        self.assertEqual(PYTHON_PLACEHOLDER, snippet["mcpServers"]["ag2c"]["command"])
        self.assertEqual(SRC_PLACEHOLDER, snippet["mcpServers"]["ag2c"]["env"]["PYTHONPATH"])
        toml = mcp_toml_block(placeholders=True)
        self.assertIn(PYTHON_PLACEHOLDER, toml)
        self.assertNotIn(mcp_stdio_command()[0], toml)
        connect = _rpc("resources/read", {"uri": CONNECT_RESOURCE_URI})["result"]
        self.assertIn(PYTHON_PLACEHOLDER, connect["contents"][0]["text"])

    def test_health_reports_launch_and_handshake(self) -> None:
        cheap = mcp_health(handshake=False, home=Path(tempfile.mkdtemp()))
        self.assertIn(cheap["status"], {"ok", "broken"})
        self.assertTrue(cheap["skills_internalized"])
        self.assertGreaterEqual(cheap["tool_count"], 8)
        self.assertIsNone(cheap["handshake"])
        live = mcp_health(handshake=True, home=Path(tempfile.mkdtemp()))
        self.assertTrue(live["python_ok"])
        self.assertTrue(live["src_ok"])
        self.assertTrue(live["ok"], live.get("error"))
        self.assertEqual("MCP 正常", live["label"])
        self.assertTrue((live.get("handshake") or {}).get("ok"))
        blocked = mcp_health(handshake=False, home=Path(tempfile.mkdtemp()), managed=False)
        self.assertFalse(blocked["ok"])
        self.assertEqual("MCP 异常", blocked["label"])
        self.assertFalse((blocked.get("guard") or {}).get("managed"))
        tool = _rpc("tools/call", {"name": "ag2c_mcp_health", "arguments": {"handshake": False}})
        payload = json.loads(tool["result"]["content"][0]["text"])
        self.assertTrue(payload["skills_internalized"])


class AsyncVerifyTests(unittest.TestCase):
    def setUp(self) -> None:
        from ag2c import mcp_server

        self.server = mcp_server
        self._jobs = dict(mcp_server._VERIFY_JOBS)
        mcp_server._VERIFY_JOBS.clear()
        self.addCleanup(self._restore_jobs)

    def _restore_jobs(self) -> None:
        self.server._VERIFY_JOBS.clear()
        self.server._VERIFY_JOBS.update(self._jobs)

    def _verify(self, cwd: Path):
        return self.server._call_verify({"cwd": str(cwd)})

    def test_fast_verify_returns_the_result_inline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch("ag2c.tasks.verify_task", return_value={"passed": True}) as mocked:
                result = self._verify(Path(directory))
            self.assertEqual({"passed": True}, result)
            self.assertEqual(1, mocked.call_count)
            self.assertEqual({}, self.server._VERIFY_JOBS)

    def test_slow_verify_returns_running_then_delivers_once(self) -> None:
        import threading

        release = threading.Event()

        def slow(_cwd):
            release.wait(10)
            return {"passed": True}

        with tempfile.TemporaryDirectory() as directory:
            cwd = Path(directory)
            with patch("ag2c.tasks.verify_task", side_effect=slow) as mocked:
                with patch.object(self.server, "VERIFY_WAIT_SECONDS", 0.05):
                    first = self._verify(cwd)
                    self.assertEqual("running", first["state"])
                    second = self._verify(cwd)  # polls the same job, no duplicate run
                    self.assertEqual("running", second["state"])
                    release.set()
                    with patch.object(self.server, "VERIFY_WAIT_SECONDS", 5):
                        third = self._verify(cwd)
            self.assertEqual({"passed": True}, third)
            self.assertEqual(1, mocked.call_count)
            self.assertEqual({}, self.server._VERIFY_JOBS)

    def test_verify_errors_surface_on_the_poll(self) -> None:
        from ag2c.errors import AG2CError

        with tempfile.TemporaryDirectory() as directory:
            with patch("ag2c.tasks.verify_task", side_effect=AG2CError("household gate blocked")):
                with self.assertRaisesRegex(AG2CError, "household gate blocked"):
                    self._verify(Path(directory))
            self.assertEqual({}, self.server._VERIFY_JOBS)


class AsyncRehomeTests(unittest.TestCase):
    def setUp(self) -> None:
        from ag2c import mcp_server

        self.server = mcp_server
        self._jobs = dict(mcp_server._REHOME_JOBS)
        mcp_server._REHOME_JOBS.clear()
        self.addCleanup(self._restore_jobs)

    def _restore_jobs(self) -> None:
        self.server._REHOME_JOBS.clear()
        self.server._REHOME_JOBS.update(self._jobs)

    def _rehome(self, cwd: Path, **extra):
        args = {"cwd": str(cwd), "id": "knowledge.pkg-a", "room": "knowledge.pkg", "subdir": "sub"}
        args.update(extra)
        return self.server._call_rehome(args)

    def test_fast_rehome_returns_the_result_inline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            done = {"merged": True, "from": "src/pkg/a.py", "to": "src/pkg/sub/a.py"}
            with patch("ag2c.rehome.rehome_file_card", return_value=done) as mocked:
                result = self._rehome(Path(directory))
            self.assertEqual(done, result)
            self.assertEqual(1, mocked.call_count)
            self.assertEqual({}, self.server._REHOME_JOBS)

    def test_slow_rehome_returns_a_job_then_delivers_once(self) -> None:
        import threading

        release = threading.Event()

        def slow(*_args, **_kwargs):
            release.wait(10)
            return {"merged": True}

        with tempfile.TemporaryDirectory() as directory:
            cwd = Path(directory)
            with patch("ag2c.rehome.rehome_file_card", side_effect=slow) as mocked:
                with patch.object(self.server, "VERIFY_WAIT_SECONDS", 0.05):
                    first = self._rehome(cwd)
                    self.assertEqual("running", first["state"])
                    job_id = first["job"]
                    second = self._rehome(cwd, job=job_id)
                    self.assertEqual("running", second["state"])
                    release.set()
                    with patch.object(self.server, "VERIFY_WAIT_SECONDS", 5):
                        third = self._rehome(cwd, job=job_id)
            self.assertEqual({"merged": True}, third)
            self.assertEqual(1, mocked.call_count)
            self.assertEqual({}, self.server._REHOME_JOBS)

    def test_rehome_errors_surface_on_the_poll(self) -> None:
        from ag2c.errors import AG2CError

        with tempfile.TemporaryDirectory() as directory:
            with patch("ag2c.rehome.rehome_file_card", side_effect=AG2CError("target file already exists")):
                with self.assertRaisesRegex(AG2CError, "target file already exists"):
                    self._rehome(Path(directory))
            self.assertEqual({}, self.server._REHOME_JOBS)

    def test_concurrent_rehome_is_refused(self) -> None:
        import threading

        release = threading.Event()

        def slow(*_args, **_kwargs):
            release.wait(5)
            return {"merged": True}

        from ag2c.errors import AG2CError

        with tempfile.TemporaryDirectory() as directory:
            cwd = Path(directory)
            with patch("ag2c.rehome.rehome_file_card", side_effect=slow):
                with patch.object(self.server, "VERIFY_WAIT_SECONDS", 0.05):
                    first = self._rehome(cwd)
                    self.assertEqual("running", first["state"])
                    with self.assertRaisesRegex(AG2CError, "another rehome is still running"):
                        self._rehome(cwd)
                    release.set()
                    with patch.object(self.server, "VERIFY_WAIT_SECONDS", 5):
                        self.assertEqual({"merged": True}, self._rehome(cwd, job=first["job"]))

    def test_unknown_job_id_is_an_error(self) -> None:
        from ag2c.errors import AG2CError

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(AG2CError, "unknown rehome job"):
                self._rehome(Path(directory), job="no-such-job")

    def test_missing_card_or_room_is_an_error(self) -> None:
        from ag2c.errors import AG2CError

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(AG2CError, "requires id"):
                self.server._call_rehome({"cwd": str(Path(directory)), "id": "", "room": ""})


if __name__ == "__main__":
    unittest.main()
