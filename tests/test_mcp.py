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
    PROCESS_STARTED_AT,
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

class LaunchSrcTests(unittest.TestCase):

    def _fixture(self, directory: str) -> tuple[Path, Path]:
        from ag2c.enrollment import enroll_project
        from support import git_project

        root = git_project(Path(directory) / "repo")
        enroll_project(root, skill_root=Path(directory) / "skills", harnesses=("agents",))
        (root / "src" / "ag2c").mkdir()  # canonical src must look like an AG2C install
        return root, root / "src"

    def test_worktree_module_redirects_to_canonical_src(self) -> None:
        from ag2c.config import discover_manifest, load_manifest
        from ag2c.mcp_server import _launch_src

        with tempfile.TemporaryDirectory() as directory:
            root, canonical_src = self._fixture(directory)
            manifest = load_manifest(discover_manifest(root))
            module_file = (
                manifest.state_dir.parent / "worktrees" / "task-x" / "src" / "ag2c" / "mcp_server.py"
            )
            module_file.parent.mkdir(parents=True)
            module_file.write_text("", encoding="utf-8")
            self.assertEqual(canonical_src.resolve(), _launch_src(module_file, root))

    def test_canonical_module_stays_put(self) -> None:
        from ag2c.mcp_server import _launch_src

        with tempfile.TemporaryDirectory() as directory:
            root, canonical_src = self._fixture(directory)
            module_file = canonical_src / "ag2c" / "mcp_server.py"
            module_file.parent.mkdir(parents=True, exist_ok=True)
            module_file.write_text("", encoding="utf-8")
            self.assertEqual(canonical_src.resolve(), _launch_src(module_file, root))

    def test_no_discoverable_project_falls_back_to_module_src(self) -> None:
        from ag2c.mcp_server import _launch_src

        with tempfile.TemporaryDirectory() as directory:
            module_file = Path(directory) / "nowhere" / "src" / "ag2c" / "mcp_server.py"
            module_file.parent.mkdir(parents=True)
            module_file.write_text("", encoding="utf-8")
            self.assertEqual(module_file.parents[1], _launch_src(module_file, Path(directory)))

    def test_non_worktree_module_never_discovers(self) -> None:
        """托盘项目栏每帧调 mcp_launch_spec；发现内部起 git 子进程（Windows 约 60ms）， 非 worktree 安装必须走快路径，完全不做 manifest 发现。"""
        from unittest.mock import patch

        from ag2c.mcp_server import _launch_src

        def _forbidden(*args: object, **kwargs: object) -> None:
            raise AssertionError("discover_manifest must not run for non-worktree installs")

        with tempfile.TemporaryDirectory() as directory:
            module_file = Path(directory) / "install" / "src" / "ag2c" / "mcp_server.py"
            module_file.parent.mkdir(parents=True)
            module_file.write_text("", encoding="utf-8")
            with patch("ag2c.config.discover_manifest", _forbidden):
                self.assertEqual(module_file.parents[1].resolve(), _launch_src(module_file, Path(directory)))

    def test_worktree_module_still_discovers(self) -> None:
        """路径里带 worktrees 时保持旧行为：发现仍会被调用（大小写不敏感）。"""
        from unittest.mock import patch

        from ag2c.mcp_server import _launch_src

        called = []

        def _spy(*args: object, **kwargs: object) -> None:
            called.append(True)
            raise RuntimeError("stop after proving discovery ran")

        with tempfile.TemporaryDirectory() as directory:
            module_file = Path(directory) / "WorkTrees" / "task-x" / "src" / "ag2c" / "mcp_server.py"
            module_file.parent.mkdir(parents=True)
            module_file.write_text("", encoding="utf-8")
            with patch("ag2c.config.discover_manifest", _spy):
                self.assertEqual(module_file.parents[1].resolve(), _launch_src(module_file, Path(directory)))
            self.assertTrue(called)


class ResultGateTests(unittest.TestCase):
    def test_task_start_schema_requires_the_portrait(self) -> None:
        start = next(item for item in tool_defs() if item["name"] == "ag2c_task_start")
        self.assertIn("portrait", start["inputSchema"]["required"])
        finish = next(item for item in tool_defs() if item["name"] == "ag2c_task_finish")
        self.assertIn("proof", finish["inputSchema"]["required"])

    def test_start_without_portrait_is_refused(self) -> None:
        from ag2c.errors import AG2CError
        from ag2c.mcp_server import _call_start
        with self.assertRaises(AG2CError) as raised:
            _call_start({"goal": "x", "paths": ["app:a.py"], "cwd": "."})
        self.assertIn("portrait", str(raised.exception).lower())

    def test_finish_without_proof_is_refused(self) -> None:
        from ag2c.errors import AG2CError
        from ag2c.mcp_server import _call_finish
        with self.assertRaises(AG2CError) as raised:
            _call_finish({"task": "t", "message": "m", "cwd": "."})
        self.assertIn("proof", str(raised.exception).lower())

    def test_write_without_cwd_is_refused(self) -> None:
        from ag2c.errors import AG2CError
        from ag2c.mcp_server import _call_apply, _call_census, _call_settle, _call_start, _cwd
        self.assertIsInstance(_cwd({"cwd": "."}), Path)
        with self.assertRaises(AG2CError) as raised:
            _cwd({}, required=True)
        self.assertIn("cwd is required", str(raised.exception))
        for fn, args in (
            (_call_apply, {"action": "add", "id": "knowledge.x", "reason": "x"}),
            (_call_start, {"goal": "x", "portrait": "x"}),
            (_call_census, {"record": True}),
            (_call_settle, {"reason": "x"}),
        ):
            with self.assertRaises(AG2CError) as raised:
                fn(args)
            self.assertIn("cwd is required", str(raised.exception))

    def test_instructions_carry_the_result_gate_discipline(self) -> None:
        self.assertIn("结果门", MCP_INSTRUCTIONS)
        self.assertIn("自证", MCP_INSTRUCTIONS)
        self.assertIn("随便的答案", MCP_INSTRUCTIONS)

class PortraitLintTests(unittest.TestCase):
    GOOD = (
        "Done looks like: 状态条开关点击后抽屉真实出现（机器验证：test_desktop 断言 toggle_dock 翻转 "
        "is_visible；实机：预览实例点击截图）。Out of result: 抽屉内容。无加料。"
    )
    def test_good_portrait_passes(self) -> None:
        from ag2c.tasks import lint_portrait
        self.assertEqual([], lint_portrait(self.GOOD))
    def test_thin_portrait_is_refused(self) -> None:
        from ag2c.tasks import lint_portrait
        violations = lint_portrait("修好它")
        self.assertTrue(any(v.startswith("too-thin") for v in violations))
    def test_missing_verification_layer_is_refused(self) -> None:
        from ag2c.tasks import lint_portrait
        portrait = "Done looks like: 抽屉可以打开关闭，状态条按钮生效，门状态行定位到对应面板，布局保持。"
        violations = lint_portrait(portrait)
        self.assertTrue(any(v.startswith("no-verification-layer") for v in violations))

    def test_vague_phrase_is_refused_and_named(self) -> None:
        from ag2c.tasks import lint_portrait

        portrait = "Done looks like: 谱系图正常工作，点击卡片详情正常显示（机器验证：测试）。"
        violations = lint_portrait(portrait)
        vague = [v for v in violations if v.startswith("vague-phrase")]
        self.assertTrue(vague)
        self.assertIn("正常工作", vague[0])

    def test_english_vague_phrase_is_refused(self) -> None:
        from ag2c.tasks import lint_portrait

        portrait = "Done looks like: the drawer works as expected after the fix (verified by tests)."
        violations = lint_portrait(portrait)
        self.assertTrue(any(v.startswith("vague-phrase") for v in violations))

    def test_constitution_named_vague_words_are_refused(self) -> None:
        from ag2c.tasks import lint_portrait

        # The constitution names 优化/完善/合理 as words that never pass.
        for word in ("优化", "完善", "合理"):
            portrait = f"Done looks like: 谱系加载性能{word}，响应更快（机器验证：测试断言）。"
            violations = lint_portrait(portrait)
            self.assertTrue(
                any(v.startswith("vague-phrase") and word in v for v in violations),
                f"{word} should be refused",
            )

    def test_negated_vague_phrase_is_exempt(self) -> None:
        from ag2c.tasks import lint_portrait

        portrait = (
            "Done looks like: 抽屉开关生效，不再是按钮变蓝但面板不出现（机器验证：test_desktop 断言；"
            "实机：点击截图对照）。无加料。"
        )
        self.assertEqual([], lint_portrait(portrait))

    def test_missing_inference_ledger_is_refused(self) -> None:
        from ag2c.tasks import lint_portrait

        portrait = "Done looks like: 抽屉开关生效（机器验证：test_desktop 断言 toggle 翻转）。"
        violations = lint_portrait(portrait)
        self.assertTrue(any(v.startswith("no-inference-ledger") for v in violations))

    def test_inferences_section_satisfies_the_ledger(self) -> None:
        from ag2c.tasks import lint_portrait

        portrait = (
            "Done looks like: 抽屉开关生效（机器验证：test_desktop 断言）。"
            "Inferences: INFERRED 用户说的抽屉指右侧详情面板。"
        )
        self.assertEqual([], lint_portrait(portrait))

    def test_inference_section_extraction(self) -> None:
        from ag2c.tasks import portrait_inference_section

        portrait = (
            "Done looks like: x（机器验证：测试）。Surfaces: verify。 "
            "Inferences: INFERRED 并行 4 路在本机安全。"
        )
        section = portrait_inference_section(portrait)
        self.assertIn("INFERRED 并行 4 路", section)
        self.assertNotIn("Done looks like", section)
        self.assertEqual("", portrait_inference_section("Done looks like: x（机器验证：测试）。无加料。"))
        self.assertEqual("", portrait_inference_section(""))

    def test_mcp_start_refuses_vague_portrait(self) -> None:
        from ag2c.errors import AG2CError
        from ag2c.mcp_server import _call_start

        with tempfile.TemporaryDirectory() as directory:
            from ag2c.enrollment import enroll_project
            from support import git_project

            root = git_project(Path(directory) / "repo")
            enroll_project(root, skill_root=Path(directory) / "skills", harnesses=("agents",))
            with self.assertRaises(AG2CError) as raised:
                _call_start(
                    {
                        "goal": "x",
                        "paths": ["app:src/value.py"],
                        "portrait": "Done looks like: 正常工作没问题（机器验证：测试）。",
                        "cwd": str(root),
                    }
                )
            self.assertIn("portrait lint failed", str(raised.exception))
            # The lint fires before any worktree is created.
            from ag2c.config import discover_manifest, load_manifest

            manifest = load_manifest(discover_manifest(root))
            worktrees = manifest.state_dir.parent / "worktrees"
            self.assertEqual([], list(worktrees.iterdir()) if worktrees.is_dir() else [])


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
        self.assertIn("verbose", properties)
        self.assertEqual("boolean", properties["verbose"]["type"])

    def test_household_tool_schema_exposes_entrypoint_checker_command(self) -> None:
        household = next(item for item in tool_defs() if item["name"] == "ag2c_household")
        properties = household["inputSchema"]["properties"]
        for key in ("entrypoint", "checker", "command"):
            self.assertIn(key, properties)
            self.assertEqual("array", properties[key]["type"])

    def test_apply_and_household_schemas_expose_provides_and_conventions(self) -> None:
        for name in ("ag2c_apply", "ag2c_household"):
            tool = next(item for item in tool_defs() if item["name"] == name)
            properties = tool["inputSchema"]["properties"]
            self.assertIn("provides", properties)
            self.assertEqual("array", properties["provides"]["type"])
            self.assertIn("conventions", properties)
            self.assertEqual("string", properties["conventions"]["type"])
            self.assertNotIn("provides", tool["inputSchema"]["required"])

    def test_instructions_teach_the_reuse_menu(self) -> None:
        result = _rpc("initialize")["result"]
        self.assertIn("reuse_menu", result["instructions"])
        self.assertIn("provides", result["instructions"])

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

    def test_health_reports_code_version_and_started_at(self):
        import ag2c

        first = mcp_health(handshake=False, home=Path(tempfile.mkdtemp()))
        second = mcp_health(handshake=False, home=Path(tempfile.mkdtemp()))
        self.assertEqual(ag2c.__version__, first["code_version"])
        self.assertEqual(PROCESS_STARTED_AT, first["started_at"])
        self.assertEqual(first["started_at"], second["started_at"])
        self.assertRegex(first["started_at"], r"^\d{4}-\d{2}-\d{2}T")
        tool = _rpc("tools/call", {"name": "ag2c_mcp_health", "arguments": {"handshake": False}})
        payload = json.loads(tool["result"]["content"][0]["text"])
        self.assertEqual(ag2c.__version__, payload["code_version"])
        self.assertEqual(PROCESS_STARTED_AT, payload["started_at"])


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
