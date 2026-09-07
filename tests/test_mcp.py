from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

import bootstrap  # noqa: F401

from ag2c.harnesses import PACKAGED_SKILLS
from ag2c.mcp_server import (
    MCP_INSTRUCTIONS,
    handle_mcp_request,
    install_mcp_clients,
    mcp_stdio_command,
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

    def test_tools_list_covers_the_skill_routes(self) -> None:
        names = {item["name"] for item in tool_defs()}
        self.assertTrue(
            {
                "ag2c_guard_status",
                "ag2c_task_start",
                "ag2c_task_verify",
                "ag2c_task_finish",
                "ag2c_census",
                "ag2c_span",
                "ag2c_household",
                "ag2c_apply",
                "ag2c_skill",
            }.issubset(names)
        )
        listed = _rpc("tools/list")["result"]["tools"]
        self.assertEqual(names, {item["name"] for item in listed})

    def test_resources_expose_packaged_skills(self) -> None:
        resources = _rpc("resources/list")["result"]["resources"]
        uris = {item["uri"] for item in resources}
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
            cursor = json.loads((home / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
            self.assertEqual(mcp_stdio_command()[0], cursor["mcpServers"]["ag2c"]["command"])
            install_mcp_clients(home=home)
            again = (home / ".grok" / "config.toml").read_text(encoding="utf-8")
            self.assertEqual(1, again.count("[mcp_servers.ag2c]"))

    def test_mcp_command_does_not_use_pythonw(self) -> None:
        command = mcp_stdio_command()
        self.assertNotIn("pythonw", command[0].lower())
        self.assertIn("mcp", command)


if __name__ == "__main__":
    unittest.main()
