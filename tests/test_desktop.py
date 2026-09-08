from __future__ import annotations

import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import bootstrap

import ag2c_gui.desktop
from ag2c_gui.desktop import DesktopServer


class DesktopBootProbeTests(unittest.TestCase):
    def test_boot_probe_script_passes_against_a_real_server(self) -> None:
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, "-B", str(root / "scripts" / "check_desktop_boot.py")],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("OK:", result.stdout)


class DesktopServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = DesktopServer(("127.0.0.1", 0), "test-token-with-at-least-24-characters")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def request(self, method: str, path: str, *, body=None, token: bool = False, origin: str | None = None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Host": f"127.0.0.1:{self.port}"}
        if token:
            headers["X-AG2C-Token"] = "test-token-with-at-least-24-characters"
        if origin:
            headers["Origin"] = origin
        payload = None
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response.status, data, dict(response.getheaders())

    def test_desktop_api_does_not_serve_html_viewer_assets(self) -> None:
        status, _, headers = self.request("GET", "/")
        self.assertEqual(404, status)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertNotIn("Set-Cookie", headers)
        status, _, _ = self.request("GET", "/assets/app.js")
        self.assertEqual(404, status)
        status, body, headers = self.request("GET", "/api/status")
        self.assertEqual(200, status)
        self.assertTrue(headers["X-AG2C-Desktop"].startswith("desktop/"))
        capabilities = json.loads(body)["capabilities"]
        self.assertEqual(["knowledge-graph", "native-ui", "project-details"], sorted(capabilities))

    def test_project_data_requires_session_token_and_same_origin(self) -> None:
        status, _, _ = self.request("GET", "/api/projects")
        self.assertEqual(401, status)
        status, _, _ = self.request("GET", "/api/projects", token=True, origin="http://example.com")
        self.assertEqual(403, status)
        with patch("ag2c_gui.desktop.managed_projects", return_value=[{"name": "Project", "root": "C:/Project"}]) as listed, patch(
            "ag2c_gui.desktop.align_managed_projects"
        ) as align:
            status, body, _ = self.request("GET", "/api/projects", token=True)
        self.assertEqual(200, status)
        payload = json.loads(body)
        self.assertEqual("Project", payload["projects"][0]["name"])
        self.assertNotIn("migrations", payload)
        self.assertIn("version", payload)
        listed.assert_called_once()
        align.assert_not_called()

    def test_cookie_does_not_authorize_project_requests(self) -> None:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request(
            "GET",
            "/api/projects",
            headers={
                "Host": f"127.0.0.1:{self.port}",
                "Cookie": "ag2c-token=test-token-with-at-least-24-characters",
            },
        )
        response = connection.getresponse()
        response.read()
        connection.close()
        self.assertEqual(401, response.status)

    def test_add_project_endpoint_returns_management_snapshot(self) -> None:
        expected = {"name": "Project", "root": "C:/Project", "state": "protected"}
        with patch("ag2c_gui.desktop.add_project", return_value=expected) as add:
            status, body, _ = self.request(
                "POST",
                "/api/projects/add",
                body={"path": "C:/Project"},
                token=True,
            )
        self.assertEqual(200, status)
        self.assertEqual(expected, json.loads(body)["project"])
        add.assert_called_once()

    def test_html_folder_browser_endpoints_are_gone(self) -> None:
        status, _, _ = self.request("POST", "/api/filesystem/list", body={"path": "C:/Project"}, token=True)
        self.assertEqual(404, status)
        status, _, _ = self.request("POST", "/api/filesystem/pick", body={}, token=True)
        self.assertEqual(404, status)
        status, _, _ = self.request("GET", "/api/session", token=True)
        self.assertEqual(404, status)
        status, _, _ = self.request("GET", "/api/projects/revision", token=True)
        self.assertEqual(404, status)
        status, _, _ = self.request("POST", "/api/evidence", body={"path": "C:/Project"}, token=True)
        self.assertEqual(404, status)

    def test_align_endpoint_runs_separately_from_the_project_list(self) -> None:
        with patch("ag2c_gui.desktop.align_managed_projects", return_value=[{"action": "aligned"}]) as align, patch(
            "ag2c_gui.desktop.managed_projects", return_value=[{"name": "Project", "root": "C:/Project"}]
        ):
            status, body, _ = self.request("POST", "/api/projects/align", body={}, token=True)
        self.assertEqual(200, status)
        payload = json.loads(body)
        self.assertEqual([{"action": "aligned"}], payload["migrations"])
        self.assertEqual("Project", payload["projects"][0]["name"])
        align.assert_called_once()

    def test_recheck_repairs_activation_before_returning_status(self) -> None:
        expected = {"name": "Project", "root": "C:/Project", "state": "protected"}
        with patch("ag2c_gui.desktop.repair_and_check_project", return_value=expected) as repair:
            status, body, _ = self.request(
                "POST",
                "/api/projects/check",
                body={"path": "C:/Project"},
                token=True,
            )
        self.assertEqual(200, status)
        self.assertEqual(expected, json.loads(body)["project"])
        repair.assert_called_once()

    def test_project_details_endpoint_returns_governance_payload(self) -> None:
        expected = {
            "available": True,
            "project": {"name": "Project"},
            "cards": [{"id": "floor.app", "type": "floor"}],
            "knowledge": [],
        }
        with patch("ag2c_gui.desktop.project_details", return_value=expected) as details:
            status, body, _ = self.request(
                "POST",
                "/api/project/details",
                body={"path": "C:/Project"},
                token=True,
            )
        self.assertEqual(200, status)
        self.assertEqual(expected, json.loads(body))
        details.assert_called_once()

    def test_project_digest_endpoint_returns_fingerprint(self) -> None:
        with patch("ag2c_gui.desktop._project_digest", return_value={"digest": "abc123", "version": "0"}) as digest:
            status, body, _ = self.request(
                "POST",
                "/api/project/digest",
                body={"path": "C:/Project"},
                token=True,
            )
        self.assertEqual(200, status)
        self.assertEqual({"digest": "abc123", "version": "0"}, json.loads(body))
        digest.assert_called_once()

    def test_serve_desktop_notifies_after_socket_is_bound(self) -> None:
        from ag2c_gui.desktop import serve_desktop

        ready = []

        def stop(port: int) -> None:
            ready.append(port)

        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        with patch("ag2c_gui.desktop.DesktopServer.serve_forever", side_effect=KeyboardInterrupt):
            self.assertEqual(
                0,
                serve_desktop(port=port, token="test-token-with-at-least-24-characters", on_ready=stop),
            )
        self.assertEqual(1, len(ready))
        self.assertGreater(ready[0], 0)


class ProjectDigestTests(unittest.TestCase):
    def test_digest_is_stable_then_tracks_state_and_head_changes(self) -> None:
        from support import git_project

        from ag2c.config import discover_manifest, load_manifest
        from ag2c.enrollment import enroll_project
        from ag2c.gitops import git
        from ag2c_gui.desktop import _project_digest

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = git_project(base / "demo")
            data = base / "ag2c-data"
            with patch.dict(os.environ, {"AG2C_DATA_ROOT": str(data)}, clear=False):
                enroll_project(root, skill_root=base / "skills", harnesses=("agents",))
                first = _project_digest(root)["digest"]
                self.assertEqual(first, _project_digest(root)["digest"])
                manifest = load_manifest(discover_manifest(root), project_root=root)
                os.utime(manifest.policy_path, ns=(1_000_000_000, 1_000_000_000))
                touched = _project_digest(root)["digest"]
                self.assertNotEqual(first, touched)
                (root / "note.txt").write_text("hello\n", encoding="utf-8")
                git(root, "add", "note.txt")
                # The enrolled guard hooks canonical commits; the test only needs HEAD to move.
                git(root, "commit", "--no-verify", "-m", "move HEAD")
                self.assertNotEqual(touched, _project_digest(root)["digest"])

    def test_tray_polls_digest_and_reloads_on_change(self) -> None:
        ui = (Path(__file__).resolve().parents[1] / "src" / "ag2c_gui" / "imgui_tray.py").read_text(encoding="utf-8")
        self.assertIn("AUTO_REFRESH_INTERVAL_S", ui)
        self.assertIn("def _maybe_auto_refresh", ui)
        self.assertIn("def _poll_digest", ui)
        self.assertIn('"POST", "api/project/digest"', ui)
        self.assertIn("state.digest", ui)
        self.assertIn("检测到项目变更，已自动刷新", ui)
        self.assertIn("_maybe_auto_refresh(state)", ui)

    def test_canonical_guard_reports_dirty_outside_task_windows(self) -> None:
        from support import git_project

        from ag2c.enrollment import enroll_project
        from ag2c.tasks import TASK_SCHEMA
        from ag2c_gui import desktop

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = git_project(base / "demo")
            data = base / "ag2c-data"
            with patch.dict(os.environ, {"AG2C_DATA_ROOT": str(data)}, clear=False):
                enroll_project(root, skill_root=base / "skills", harnesses=("agents",))
                desktop._GUARD_CACHE.clear()
                clean = desktop._canonical_guard(root)
                self.assertEqual({"canonicalDirty": False, "openTasks": 0}, clean)

                (root / "src" / "value.py").write_text("VALUE = 2\n", encoding="utf-8")
                desktop._GUARD_CACHE.clear()
                dirty = desktop._canonical_guard(root)
                self.assertTrue(dirty["canonicalDirty"])
                self.assertEqual(0, dirty["openTasks"])

                from ag2c.config import discover_manifest, load_manifest

                manifest = load_manifest(discover_manifest(root), project_root=root)
                tasks_dir = manifest.state_dir / "tasks"
                tasks_dir.mkdir(parents=True, exist_ok=True)
                (tasks_dir / "t1.json").write_text(
                    json.dumps({"schema": TASK_SCHEMA, "id": "t1", "state": "open"}), encoding="utf-8"
                )
                desktop._GUARD_CACHE.clear()
                tasked = desktop._canonical_guard(root)
                self.assertTrue(tasked["canonicalDirty"])
                self.assertEqual(1, tasked["openTasks"])

    def test_canonical_guard_is_ttl_cached_and_never_breaks_digest(self) -> None:
        from support import git_project

        from ag2c.enrollment import enroll_project
        from ag2c_gui import desktop

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = git_project(base / "demo")
            data = base / "ag2c-data"
            with patch.dict(os.environ, {"AG2C_DATA_ROOT": str(data)}, clear=False):
                enroll_project(root, skill_root=base / "skills", harnesses=("agents",))
                desktop._GUARD_CACHE.clear()
                calls = []
                with patch("ag2c.gitops.status_entries", side_effect=lambda p: calls.append(p) or []):
                    first = desktop._canonical_guard(root)
                    second = desktop._canonical_guard(root)
                self.assertEqual(first, second)
                self.assertEqual(1, len(calls))
                desktop._GUARD_CACHE.clear()
                with patch("ag2c.gitops.status_entries", side_effect=OSError("git gone")):
                    broken = desktop._canonical_guard(root)
                self.assertTrue(broken.get("error"))
                payload = desktop._project_digest(root)
                self.assertIn("digest", payload)
                self.assertIn("guard", payload)

    def test_tray_watchdog_banner_source(self) -> None:
        ui = (Path(__file__).resolve().parents[1] / "src" / "ag2c_gui" / "imgui_tray.py").read_text(encoding="utf-8")
        self.assertIn("guard_warning", ui)
        self.assertIn("canonicalDirty", ui)
        self.assertIn("看门狗报警", ui)
        self.assertIn("canonical 在非任务窗口被修改", ui)


class TrayHostSourceTests(unittest.TestCase):
    def test_tray_host_is_hello_imgui_without_webview2_or_pyside(self) -> None:
        root = Path(__file__).resolve().parents[1]
        ui = (root / "src" / "ag2c_gui" / "imgui_tray.py").read_text(encoding="utf-8")
        host = (root / "src" / "ag2c_gui" / "tray_host.py").read_text(encoding="utf-8")
        caption = (root / "src" / "ag2c_gui" / "tray_caption_win32.py").read_text(encoding="utf-8")
        management = (root / "src" / "ag2c" / "management.py").read_text(encoding="utf-8")
        tasks = (root / "src" / "ag2c" / "tasks.py").read_text(encoding="utf-8")
        households = (root / "src" / "ag2c" / "households.py").read_text(encoding="utf-8")
        entry = (root / "packaging" / "windows" / "tray.py").read_text(encoding="utf-8")
        build = (root / "scripts" / "build_windows_portable.ps1").read_text(encoding="utf-8")
        portable = (root / "scripts" / "prepare_portable.ps1").read_text(encoding="utf-8")
        self.assertIn("from imgui_bundle import hello_imgui", ui)
        self.assertIn("DockableWindow", ui)
        self.assertIn("portable_file_dialogs", ui)
        self.assertIn("application_start", ui)
        self.assertIn("enable_viewports = False", ui)
        self.assertIn("AutoGovern2Code/tray-v14.ini", ui)
        self.assertIn("borderless = False", ui)
        self.assertNotIn("_title_bar_buttons", ui)
        self.assertNotIn("_chrome_button", ui)
        self.assertNotIn("winchrome", ui)
        self.assertIn("show_menu_bar = False", ui)
        self.assertNotIn("show_menus", ui)
        self.assertIn("##file-tree-body", ui)
        self.assertIn("no_collapse", ui)
        self.assertIn("get_hovered_node", ui)
        self.assertIn("card_matching_lineage", ui)
        self.assertIn("add_bezier_cubic", ui)
        self.assertIn("lineage_expanded", ui)
        self.assertIn("small_button", ui)
        self.assertNotIn("##span-", ui)
        self.assertIn("layout_lineage_view", ui)
        self.assertIn("outward_hull", ui)
        self.assertIn("卡名就是摘要", ui)
        self.assertIn("详细设计", ui)
        self.assertIn("序号按层写", ui)
        self.assertIn("1-1-1", ui)
        self.assertNotIn('text_disabled("摘要")', ui)
        self.assertIn("outward_hull", (root / "src" / "ag2c_gui" / "graph.py").read_text(encoding="utf-8"))
        self.assertIn("exp:", ui)
        self.assertIn("{LINEAGE_PROJECT_ID}", ui)
        self.assertIn("highlight_card_keys", ui)
        self.assertIn("_reveal_lineage_owners", ui)
        self.assertIn("归属知识卡", ui)
        self.assertNotIn("LINEAGE_MODULE_HEADER", ui)
        self.assertIn('settings_file = ""', ui)
        self.assertIn("center_only", ui)
        self.assertIn("canvas_size_mode", ui)
        self.assertIn("anti_aliasing_samples", ui)
        self.assertIn("rasterizer_density", ui)
        self.assertIn("anti_aliased_lines_use_tex", ui)
        self.assertIn("FileTreeSpace", ui)
        self.assertIn("CardSpace", ui)
        self.assertIn("_gui_project_bar", ui)
        self.assertIn("_gui_gate_strip", ui)
        self.assertIn("AI 入口", ui)
        self.assertIn("检测 MCP", ui)
        self.assertIn("复制连接说明", ui)
        self.assertNotIn("复制提示词", ui)
        self.assertIn("if migrations:", ui)
        self.assertIn("status = project_list_item(root)", management)
        self.assertIn("_CENSUS_CACHE", households)
        evidence_src = tasks[tasks.find("def evidence(") : tasks.find("def evidence(") + 1800]
        self.assertIn("if verify_local:", evidence_src)
        self.assertLess(evidence_src.find("if verify_local:"), evidence_src.find("census_report"))
        self.assertNotIn("已控制", ui)
        self.assertNotIn("交付门禁已接通", ui)
        self.assertNotIn('"id": "delivery"', host)
        self.assertNotIn('"label": "交付"', host)
        self.assertIn("mcp_health_snapshot", ui)
        self.assertIn("mcp_entry_text", ui)
        self.assertIn("set_clipboard_text", ui)
        self.assertIn("实际记录", ui)
        self.assertIn("_lineage_is_marked", ui)
        self.assertIn("_lineage_card_colors", ui)
        self.assertIn("0.45, 0.72, 0.98", ui)
        self.assertIn("begin_combo", ui)
        self.assertIn('layout_name = "tray-v14"', ui)
        self.assertIn('split("MainDockSpace", "FileTreeSpace", imgui.Dir.left, 0.26, tree_lock)', ui)
        self.assertNotIn("_caption_place", ui)
        self.assertNotIn('begin_menu("项目")', ui)
        self.assertIn('split("MainDockSpace", "InspectorSpace", imgui.Dir.right, 0.38)', ui)
        self.assertNotIn("borderless_movable", ui)
        self.assertNotIn("0x00A1", caption)
        self.assertNotIn("_caption_hit", ui)
        self.assertIn("from .tray_caption_win32 import", ui)
        self.assertIn("viewpad:tl", ui)
        self.assertIn("gw * 0.12", ui)
        self.assertIn("lineage_fit_frames", ui)
        self.assertNotIn("is_mouse_dragging(0, 6.0)", ui)
        self.assertNotIn("ag2c-caption-proof.txt", caption)
        self.assertNotIn("glfwRestoreWindow", caption)
        self.assertNotIn("glfwMaximizeWindow", caption)
        self.assertIn('"mode": inspect_mode', ui)
        self.assertIn("navigate_to_content(0.0)", ui)
        self.assertNotIn("center_node_on_screen", ui)
        self.assertIn("drag_button_index = 2", ui)
        self.assertIn("select_button_index = 2", ui)
        self.assertIn("selected_node_border_width = 0.0", ui)
        self.assertIn("clear_selection", ui)
        self.assertIn("add_text", ui)
        self.assertIn("pan_lineage=False", ui)
        self.assertIn("navigate_to_selection(False, 0.0)", ui)
        self.assertIn("CenterNodeOnScreen moves the node", ui)
        self.assertIn("0x00292421", caption)
        self.assertIn("glfwGetWin32Window", caption)
        self.assertIn("set_scroll_here_y(0.0)", ui)
        self.assertIn("set_scroll_y", ui)
        self.assertNotIn("ShowWindow", caption)
        self.assertIn("coverage_scroll_key", host)
        self.assertIn("fps_idle = 60.0", ui)
        self.assertIn("show_status_fps = True", ui)
        self.assertIn("framerate", ui)
        self.assertIn("frame_ms", ui)
        self.assertIn("def audit(", ui)
        self.assertIn("audit_open", ui)
        self.assertIn("def _gui_audit(", ui)
        self.assertIn('small_button("操作日志")', ui)
        self.assertIn('begin("操作日志"', ui)
        self.assertIn("post_render_dockable_windows", ui)
        self.assertIn("WindowFlags_.no_docking", ui)
        self.assertIn("ag2c-audit.log", ui)
        self.assertNotIn('window("操作日志"', ui)
        self.assertIn("def _gui_panels(", ui)
        self.assertIn("panel_open", ui)
        self.assertIn("def _refresh_panel(", ui)
        self.assertIn("def _gate_panel_content(", ui)
        self.assertIn("def _records_panel_content(", ui)
        self.assertIn("def _work_panel_content(", ui)
        self.assertNotIn("_inspect_gate", ui)
        self.assertIn('GATE_BUTTON_LABELS = {"gate": "MCP 链接"', ui)
        self.assertIn("list_journals", ui)
        self.assertIn('"journal": journal', ui)
        self.assertIn('begin_child("##records-body"', ui)
        self.assertIn("def _short_time(", ui)
        self.assertIn("_cached_tree", ui)
        self.assertIn("anti_aliasing_samples = 4", ui)
        self.assertIn("config_dpi_scale_fonts", ui)
        self.assertIn("lineage_layout_key", ui)
        self.assertNotIn("begin_create", ui)
        self.assertNotIn("begin_pin", ui)
        self.assertNotIn("set_group_size", ui)
        self.assertNotIn("ed.group(", ui)
        self.assertIn("谱系", ui)
        self.assertNotIn("ProjectSpace", ui)
        self.assertNotIn("LineageSpace", ui)
        self.assertIn('window("谱系", "MainDockSpace"', ui)
        self.assertIn('window("详情", "InspectorSpace"', ui)
        self.assertIn('window("知识卡片", "CardSpace"', ui)
        self.assertIn('window("文件树", "FileTreeSpace"', ui)
        self.assertNotIn('window("项目"', ui)
        self.assertNotIn('window("详情", "MainDockSpace"', ui)
        self.assertNotIn('window("详情", "CardSpace"', ui)
        self.assertNotIn('window("详情", "RightStack"', ui)
        self.assertIn("imgui_node_editor", ui)
        self.assertIn("build_lineage", ui)
        self.assertIn("lineage_nav_id", ui)
        self.assertNotIn("set_current_editor(None)", ui)
        self.assertNotIn("imguizmo", ui)
        self.assertNotIn("immvision", ui)
        self.assertIn('window("知识卡片", "CardSpace"', ui)
        self.assertNotIn('menu_item("添加项目", None', ui)
        self.assertIn("正在重新扫描", ui)
        self.assertIn("def _gui_splash(", ui)
        self.assertIn("##splash", ui)
        self.assertIn("legacy_size", ui)
        self.assertIn("add_text(font, title_size", ui)
        self.assertIn("imgui.dummy(imgui.ImVec2(width, height))", ui)
        self.assertIn("WindowFlags_.no_inputs", ui)
        self.assertNotIn("_scan_overlay", ui)
        self.assertIn("refresh=True", ui)
        self.assertIn("DwmSetWindowAttribute", caption)
        self.assertIn("set_next_item_open(True)", ui)
        self.assertIn("prefix in force_open", ui)
        self.assertIn("restore_previous_geometry = False", ui)
        self.assertNotIn("show_view_menu", ui)
        self.assertIn("_dialog_lock", ui)
        self.assertIn("enable_idling = False", ui)
        self.assertIn("background_color = (0.13, 0.14, 0.16, 1.0)", ui)
        self.assertIn("photoshop_style", ui)
        self.assertIn("from ag2c_gui.imgui_tray import main", entry)
        self.assertIn("packaging\\windows\\tray.py", build)
        self.assertIn("NOTICE-imgui.txt", build)
        self.assertIn("prepare_portable.ps1", build)
        self.assertIn("AutoGovern2Code-Portable-Windows-x64.zip", build)
        self.assertIn("tray-host", portable)
        self.assertIn("portable.ini", portable)
        self.assertIn("--portable", host)
        self.assertIn("portable.ini", host)
        launcher = (root / "start-tray.bat").read_text(encoding="utf-8")
        self.assertIn("packaging\\windows\\tray.py", launcher)
        self.assertIn("imgui-bundle", launcher)
        self.assertIn("pythonw.exe", launcher)
        self.assertIn("AG2C_PORTABLE", launcher)
        self.assertIn("AG2C_DATA_ROOT", launcher)
        self.assertIn("portable.ini", launcher)
        self.assertIn("--portable", launcher)
        ignore = (root / ".gitignore").read_text(encoding="utf-8")
        enroll = (root / "src" / "ag2c" / "enrollment.py").read_text(encoding="utf-8")
        self.assertIn("/portable.ini", ignore)
        self.assertIn(".grok/", ignore)
        self.assertNotIn("commit or stash before enrolling", enroll)
        self.assertIn("def issue_label(", host)
        self.assertIn("def skill_prompt_text(", host)
        cli = (root / "src" / "ag2c" / "cli.py").read_text(encoding="utf-8")
        self.assertIn('skill_commands.add_parser("prompt")', cli)
        self.assertIn('skill_commands.add_parser("version"', cli)
        self.assertIn("SKILL_ENTRY_PROMPT", (root / "src" / "ag2c" / "harnesses.py").read_text(encoding="utf-8"))
        self.assertIn("timeout=300", host)
        self.assertIn("imgui.text_wrapped(error)", ui)
        self.assertIn('("placeholder", "占位")', host)
        self.assertIn("入学占位，还没有说清这个目录", host)
        self.assertIn("_lineage_status_color", ui)
        self.assertIn("ensure_portable_archive", (root / "src" / "ag2c_gui" / "desktop.py").read_text(encoding="utf-8"))
        storage = (root / "src" / "ag2c" / "storage.py").read_text(encoding="utf-8")
        self.assertIn("rebind_portable_git_enrollment", storage)
        self.assertIn("relocate_installed_worktrees", storage)
        self.assertIn('ignore=shutil.ignore_patterns("worktrees", "webview2", "__pycache__")', storage)
        self.assertIn("AG2C_CHECK", launcher)
        self.assertIn('"%AG2C_CHECK%" -c "from imgui_bundle import hello_imgui"', launcher)
        self.assertIn("hidden_process_kwargs", host)
        self.assertIn("_windowless_python", host)
        self.assertIn("def _bind_kill_on_close(", host)
        self.assertIn("AssignProcessToJobObject", host)
        self.assertIn("JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000", host)
        self.assertIn("_bind_kill_on_close(process)", host)
        self.assertNotIn("post_init = lambda: _start_backend(state)", ui)
        self.assertIn("state.run_job(lambda: _start_backend(state))", ui)
        self.assertLess(ui.index("state.run_job(lambda: _start_backend(state))"), ui.index("hello_imgui.run(runner)"))
        self.assertFalse((root / "src" / "ag2c" / "qt_tray.py").exists())
        self.assertFalse((root / "src" / "ag2c" / "ui").exists())
        self.assertFalse((root / "start-governance-viewer.cmd").exists())
        self.assertFalse((root / "打开管理界面.bat").exists())


class TrayFontTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows CJK fonts live under C:\\Windows\\Fonts")
    def test_windows_cjk_font_file_exists(self) -> None:
        from ag2c_gui.imgui_tray import cjk_font_path

        found = cjk_font_path()
        self.assertIsNotNone(found)
        assert found is not None
        self.assertTrue(found.is_file())
        self.assertEqual("C:\\Windows\\Fonts", str(found.parent))

    @unittest.skipUnless(os.name == "nt", "Windows CJK fonts live under C:\\Windows\\Fonts")
    def test_load_fonts_uses_filesystem_cjk_as_default(self) -> None:
        from ag2c_gui.imgui_tray import _load_fonts, cjk_font_path

        loaded: list[dict[str, object]] = []

        class Params:
            def __init__(self) -> None:
                self.inside_assets = True
                self.merge_to_last_font = False

        hello = MagicMock()
        hello.FontLoadingParams = Params

        def load_font(path: str, size: float, params: Params | None = None) -> None:
            loaded.append(
                {
                    "path": path,
                    "size": size,
                    "inside": None if params is None else params.inside_assets,
                    "merge": None if params is None else params.merge_to_last_font,
                }
            )

        hello.load_font.side_effect = load_font
        bundle = ModuleType("imgui_bundle")
        bundle.hello_imgui = hello  # type: ignore[attr-defined]
        bundle.imgui = MagicMock()  # type: ignore[attr-defined]
        with patch.dict(sys.modules, {"imgui_bundle": bundle, "imgui_bundle.hello_imgui": hello}):
            _load_fonts()
        cjk = cjk_font_path()
        self.assertIsNotNone(cjk)
        assert cjk is not None
        self.assertGreaterEqual(len(loaded), 1)
        self.assertEqual(str(cjk), loaded[0]["path"])
        self.assertFalse(loaded[0]["inside"])
        self.assertFalse(loaded[0]["merge"])
        self.assertTrue(any(item["merge"] and "fontawesome" in str(item["path"]) for item in loaded[1:]))
        hello.imgui_default_settings.load_default_font_with_font_awesome_icons.assert_not_called()


class TraySelectionTests(unittest.TestCase):
    def test_duplicate_titles_get_distinct_widget_ids(self) -> None:
        from ag2c_gui.imgui_tray import node_key, widget_id

        label = "ADOPTION.md  ·  在册"
        left = widget_id(label, node_key({"title": "ADOPTION.md", "path": "docs/ADOPTION.md"}))
        right = widget_id(label, node_key({"title": "ADOPTION.md", "path": "docs/zh-CN/ADOPTION.md"}))
        self.assertNotEqual(left, right)
        self.assertTrue(left.startswith(label))
        self.assertIn("docs/ADOPTION.md", left)
        self.assertIn("docs/zh-CN/ADOPTION.md", right)

    def test_tray_hides_nav_cursor_and_uses_unique_selectable_ids(self) -> None:
        ui = (Path(__file__).resolve().parents[1] / "src" / "ag2c_gui" / "imgui_tray.py").read_text(encoding="utf-8")
        self.assertIn("set_nav_cursor_visible(False)", ui)
        self.assertIn("Col_.nav_cursor", ui)
        self.assertIn("widget_id(label, root)", ui)
        self.assertIn("widget_id(label, key)", ui)
        self.assertIn("inspect_key", ui)
        self.assertIn("file_tree_children", ui)
        self.assertNotIn("open_on_arrow", ui)
        self.assertIn("set_next_item_open", ui)
        self.assertIn("设计思路", ui)
        self.assertIn("未认领", ui)
        self.assertIn("同类", ui)
        self.assertIn("治理文件", ui)
        self.assertIn("def _selectable(", ui)
        self.assertIn("_selectable(widget_id(rel, \"gov:\" + rel))", ui)


class TrayHostHelperTests(unittest.TestCase):
    def test_coverage_filter_keeps_exploring_cards(self) -> None:
        from ag2c_gui.tray_host import coverage_rows, node_matches

        details = {
            "graph": {
                "headline": "对照",
                "nodes": [
                    {"kind": "knowledge", "id": "k1", "title": "frontend", "flags": ["exploring"], "path": "app:src"},
                    {"kind": "file", "path": "app:src/main.py", "flags": ["exploring"]},
                    {"kind": "file", "path": "app:docs/readme.md", "flags": ["unowned"]},
                ],
            }
        }
        files, cards, headline = coverage_rows(details, "", "exploring")
        self.assertEqual("对照", headline)
        self.assertEqual(["src/main.py"], [path for path, _ in files])
        self.assertEqual(["k1"], [card["id"] for card in cards])
        self.assertTrue(node_matches(details["graph"]["nodes"][0], "front", "exploring"))
        self.assertFalse(node_matches(details["graph"]["nodes"][2], "", "exploring"))

    def test_placeholder_filter_excludes_exploring_and_inspect_explains_enrollment(self) -> None:
        from ag2c_gui.tray_host import FILTERS, claim_label, coverage_rows, inspect_card, node_matches

        self.assertIn(("placeholder", "占位"), FILTERS)
        details = {
            "graph": {
                "headline": "对照",
                "nodes": [
                    {
                        "kind": "knowledge",
                        "id": "knowledge.src",
                        "title": "src exploring household",
                        "flags": ["placeholder"],
                        "statusTag": "placeholder",
                        "statusLabel": "占位",
                        "path": "src/**",
                    },
                    {
                        "kind": "knowledge",
                        "id": "knowledge.shell",
                        "title": "Shell",
                        "flags": ["exploring"],
                        "statusTag": "exploring",
                        "statusLabel": "开工",
                        "path": "src/shell/**",
                    },
                    {
                        "kind": "file",
                        "path": "app:src/ag2c/graph.py",
                        "flags": ["placeholder"],
                        "coveredBy": ["src exploring household"],
                        "claimLabels": ["占位 · src"],
                    },
                    {
                        "kind": "file",
                        "path": "app:src/shell/app.py",
                        "flags": ["exploring"],
                        "coveredBy": ["Shell"],
                    },
                ],
            }
        }
        files, cards, _headline = coverage_rows(details, "", "placeholder")
        self.assertEqual(["knowledge.src"], [card["id"] for card in cards])
        self.assertEqual(["src/ag2c/graph.py"], [path for path, _ in files])
        exploring_files, exploring_cards, _ = coverage_rows(details, "", "exploring")
        self.assertEqual(["knowledge.shell"], [card["id"] for card in exploring_cards])
        self.assertEqual(["src/shell/app.py"], [path for path, _ in exploring_files])
        self.assertTrue(node_matches(details["graph"]["nodes"][0], "", "placeholder"))
        self.assertFalse(node_matches(details["graph"]["nodes"][1], "", "placeholder"))
        self.assertEqual("占位 · src", claim_label(details["graph"]["nodes"][2]))
        inspected = inspect_card(details["graph"]["nodes"][0], files)
        self.assertEqual("占位", inspected["status"])
        self.assertEqual("入学占位，还没有说清这个目录", inspected["message"])
        self.assertNotIn("未普查", inspected["status"])
        self.assertNotIn("未普查", inspected["message"])

    def test_lineage_view_pads_leave_more_space_on_the_left(self) -> None:
        from ag2c_gui.imgui_tray import _lineage_view_pads

        pads = _lineage_view_pads(
            [
                {"x": 64.0, "y": 32.0, "width": 200.0, "height": 48.0},
                {"x": 336.0, "y": 32.0, "width": 200.0, "height": 280.0},
            ]
        )
        assert pads is not None
        graph_left, graph_right = 64.0, 536.0
        self.assertGreater(graph_left - pads[0], pads[2] - graph_right)

    def test_lineage_node_matches_knowledge_card_by_id_or_title(self) -> None:
        from ag2c_gui.tray_host import card_matching_lineage

        cards = [{"kind": "knowledge", "id": "knowledge.http", "title": "HTTP 与 Agent 协作接口"}]
        by_id = card_matching_lineage(cards, {"id": "knowledge.http", "title": "other"})
        by_title = card_matching_lineage(cards, {"id": "gap:x", "title": "HTTP 与 Agent 协作接口"})
        self.assertEqual("knowledge.http", by_id["id"])
        self.assertEqual("knowledge.http", by_title["id"])
        self.assertIsNone(card_matching_lineage(cards, {"id": "missing", "title": "nope"}))

    def test_file_tree_lets_src_open_nested_children(self) -> None:
        from ag2c_gui.tray_host import file_tree_children

        tree = file_tree_children(
            [
                ("README.md", {"kind": "file", "title": "README.md", "path": "app:README.md"}),
                ("src/ag2c/gitops.py", {"kind": "file", "title": "gitops.py", "path": "app:src/ag2c/gitops.py"}),
                ("src/ag2c/imgui_tray.py", {"kind": "file", "title": "imgui_tray.py", "path": "app:src/ag2c/imgui_tray.py"}),
            ]
        )
        root_names = [name for name, kind, _prefix, _node in tree[""]]
        self.assertEqual(["src", "README.md"], root_names)
        self.assertEqual("dir", tree[""][0][1])
        self.assertEqual(["ag2c"], [name for name, _kind, _prefix, _node in tree["src"]])
        nested = [name for name, kind, _prefix, _node in tree["src/ag2c"]]
        self.assertEqual(["gitops.py", "imgui_tray.py"], nested)
        self.assertTrue(all(kind == "file" for _name, kind, _prefix, _node in tree["src/ag2c"]))

    def test_file_and_card_focus_are_bidirectional(self) -> None:
        from ag2c_gui.tray_host import claim_label, coverage_scroll_key, files_for_card, focus_card, focus_file, peer_rels

        gitops = {
            "kind": "file",
            "id": "file:app:src/ag2c/gitops.py",
            "title": "gitops.py",
            "path": "app:src/ag2c/gitops.py",
            "coveredBy": ["源码治理"],
            "summary": "src/ag2c/gitops.py",
        }
        tray = {
            "kind": "file",
            "id": "file:app:src/ag2c/imgui_tray.py",
            "title": "imgui_tray.py",
            "path": "app:src/ag2c/imgui_tray.py",
            "coveredBy": ["源码治理"],
            "summary": "src/ag2c/imgui_tray.py",
        }
        util = {
            "kind": "file",
            "id": "file:app:src/ag2c/util.py",
            "title": "util.py",
            "path": "app:src/ag2c/util.py",
            "coveredBy": [],
            "summary": "src/ag2c/util.py",
        }
        both = {
            "kind": "file",
            "id": "file:app:src/shared.py",
            "title": "shared.py",
            "path": "app:src/shared.py",
            "coveredBy": ["源码治理", "前端画布"],
        }
        card = {
            "kind": "knowledge",
            "id": "knowledge.src",
            "title": "源码治理",
            "summary": "Hello ImGui 托盘只做文件与知识卡对照，不嵌 3D。",
            "flags": [],
            "statusLabel": "在册",
        }
        empty = {
            "kind": "knowledge",
            "id": "knowledge.docs",
            "title": "文档站",
            "summary": "文档站尚未落到代码文件。",
            "flags": ["exploring"],
            "statusLabel": "开工",
        }
        files = [
            ("src/ag2c/gitops.py", gitops),
            ("src/ag2c/imgui_tray.py", tray),
            ("src/ag2c/util.py", util),
            ("src/shared.py", both),
        ]
        cards = [card, empty]
        self.assertEqual("源码治理", claim_label(gitops))
        self.assertEqual("未认领", claim_label(util))
        self.assertEqual("重复认领", claim_label(both))
        self.assertEqual(
            ["src/ag2c/gitops.py", "src/ag2c/imgui_tray.py", "src/shared.py"],
            files_for_card(files, card),
        )
        self.assertEqual(["src/ag2c/gitops.py", "src/ag2c/imgui_tray.py"], peer_rels(files, gitops))
        self.assertEqual([], peer_rels(files, util))
        picked = focus_file(files, cards, "src/ag2c/imgui_tray.py")
        assert picked is not None
        self.assertEqual("src/ag2c/imgui_tray.py", picked["selected_file"])
        self.assertEqual("knowledge.src", picked["selected_card_key"])
        self.assertEqual({"knowledge.src"}, picked["highlight_card_keys"])
        self.assertEqual(["knowledge.src"], picked["lineage_nav_ids"])
        self.assertEqual({"src/ag2c/imgui_tray.py"}, picked["highlight_paths"])
        self.assertIn("src", picked["force_open"])
        self.assertIn("src/ag2c", picked["force_open"])
        inspect = picked["inspect"]
        self.assertEqual("file", inspect["mode"])
        self.assertEqual("源码治理", inspect["claim"])
        self.assertIn("不嵌 3D", inspect["summary"])
        self.assertEqual([{"id": "knowledge.src", "title": "源码治理"}], inspect["cards"])
        self.assertEqual([], inspect["peers"])
        both_focus = focus_file(files, cards, "src/shared.py")
        assert both_focus is not None
        self.assertIn("knowledge.src", both_focus["highlight_card_keys"])
        self.assertEqual("knowledge.src", both_focus["selected_card_key"])
        titles = [item["title"] for item in both_focus["inspect"]["cards"]]
        self.assertIn("源码治理", titles)
        self.assertIn("前端画布", titles)
        unclaimed = focus_file(files, cards, "src/ag2c/util.py")
        assert unclaimed is not None
        self.assertEqual("", unclaimed["selected_card_key"])
        self.assertEqual(set(), unclaimed["highlight_paths"])
        self.assertEqual("未认领", unclaimed["inspect"]["claim"])
        from_card = focus_card(files, card)
        self.assertEqual("knowledge.src", from_card["selected_card_key"])
        self.assertEqual("", from_card["selected_file"])
        self.assertEqual({"src/ag2c/gitops.py", "src/ag2c/imgui_tray.py", "src/shared.py"}, from_card["highlight_paths"])
        self.assertEqual({"src", "src/ag2c"}, from_card["force_open"])
        self.assertNotIn("tests", from_card["force_open"])
        self.assertEqual("src", from_card["scroll_file_key"])
        self.assertEqual("src/ag2c", picked["scroll_file_key"])
        empty_focus = focus_card(files, empty)
        self.assertEqual(set(), empty_focus["highlight_paths"])
        self.assertEqual("", empty_focus["scroll_file_key"])
        self.assertEqual("这张卡还没有落到文件树上的代码文件", empty_focus["inspect"]["message"])
        self.assertEqual(
            "prototypes/demo-free-layout",
            coverage_scroll_key(
                [
                    ("prototypes/demo-free-layout/app.tsx", {}),
                    ("prototypes/demo-free-layout/src/editor.tsx", {}),
                    ("services/foo.ts", {}),
                ],
                {
                    "prototypes/demo-free-layout/app.tsx",
                    "prototypes/demo-free-layout/src/editor.tsx",
                },
            ),
        )

    def test_file_tree_click_uses_file_card_not_the_parent_room(self) -> None:
        from ag2c_gui.tray_host import focus_card, focus_file

        household = {
            "kind": "knowledge",
            "id": "knowledge.ag2c",
            "title": "src/ag2c package",
            "summary": "本卡不是设计思路。",
            "jurisdiction": {"span": "file"},
            "scopes": [{"include": ["src/ag2c/**"], "exclude": ["src/ag2c/skills/**"]}],
        }
        file_card = {
            "kind": "knowledge",
            "id": "knowledge.ag2c-cli",
            "title": "ag2c command surface",
            "summary": "argparse 命令面。",
            "scopes": [{"include": ["src/ag2c/cli.py"]}],
            "references": ["src/ag2c/cli.py"],
        }
        cli = {
            "kind": "file",
            "id": "file:app:src/ag2c/cli.py",
            "title": "cli.py",
            "path": "app:src/ag2c/cli.py",
            "coveredBy": ["ag2c command surface"],
            "parentCard": "knowledge.ag2c-cli",
            "summary": "src/ag2c/cli.py",
        }
        tasks = {
            "kind": "file",
            "id": "file:app:src/ag2c/tasks.py",
            "title": "tasks.py",
            "path": "app:src/ag2c/tasks.py",
            "coveredBy": ["task worktree lifecycle"],
            "parentCard": "knowledge.ag2c-tasks",
            "summary": "src/ag2c/tasks.py",
        }
        files = [("src/ag2c/cli.py", cli), ("src/ag2c/tasks.py", tasks)]
        cards = [household, file_card]
        picked = focus_file(files, cards, "src/ag2c/cli.py")
        assert picked is not None
        self.assertEqual("knowledge.ag2c-cli", picked["selected_card_key"])
        self.assertEqual({"src/ag2c/cli.py"}, picked["highlight_paths"])
        self.assertNotIn("src/ag2c/tasks.py", picked["highlight_paths"])
        self.assertIn("argparse 命令面", picked["inspect"]["summary"])
        self.assertNotIn("本卡不是设计思路", picked["inspect"]["summary"])
        room = focus_card(files, household)
        self.assertEqual({"src/ag2c/cli.py", "src/ag2c/tasks.py"}, room["highlight_paths"])
        self.assertEqual("knowledge.ag2c", room["selected_card_key"])

    def test_leftover_parent_click_does_not_focus_excluded_child_files(self) -> None:
        from ag2c_gui.tray_host import files_for_card, focus_card

        leftover = {
            "kind": "knowledge",
            "id": "knowledge.src",
            "title": "src leftover parent",
            "summary": "empty parent after carving src/ag2c",
            "jurisdiction": {"span": "folder"},
            "span": "folder",
            "scopes": [{"includes": ["src/**"], "excludes": ["src/ag2c/**"]}],
        }
        household = {
            "kind": "knowledge",
            "id": "knowledge.ag2c",
            "title": "src/ag2c package",
            "jurisdiction": {"span": "file"},
            "scopes": [{"include": ["src/ag2c/**"], "exclude": ["src/ag2c/skills/**"]}],
        }
        cli = {
            "kind": "file",
            "id": "file:app:src/ag2c/cli.py",
            "title": "cli.py",
            "path": "app:src/ag2c/cli.py",
            "coveredBy": ["ag2c command surface"],
            "parentCard": "knowledge.ag2c-cli",
            "summary": "src/ag2c/cli.py",
        }
        files = [("src/ag2c/cli.py", cli)]
        self.assertEqual([], files_for_card(files, leftover))
        self.assertEqual(["src/ag2c/cli.py"], files_for_card(files, household))
        leftover_focus = focus_card(files, leftover)
        self.assertEqual(set(), leftover_focus["highlight_paths"])
        self.assertEqual("这张卡还没有落到文件树上的代码文件", leftover_focus["inspect"]["message"])
        room = focus_card(files, household)
        self.assertEqual({"src/ag2c/cli.py"}, room["highlight_paths"])

    def test_card_list_hides_zaice_and_zero_file_counts(self) -> None:
        from ag2c_gui.tray_host import card_list_label, inspect_card, lineage_subtitle

        household = {
            "kind": "knowledge",
            "id": "knowledge.ag2c",
            "title": "src/ag2c package",
            "jurisdiction": {"span": "file"},
            "span": "file",
            "statusLabel": "在册",
            "flags": [],
        }
        leftover = {
            "kind": "knowledge",
            "id": "knowledge.src",
            "title": "src leftover parent",
            "jurisdiction": {"span": "folder"},
            "span": "folder",
            "statusTag": "placeholder",
            "statusLabel": "占位",
            "flags": ["placeholder"],
        }
        file_card = {
            "kind": "knowledge",
            "id": "knowledge.ag2c-cli",
            "title": "命令面参数解析",
            "statusLabel": "在册",
            "flags": [],
        }
        readme = {
            "kind": "knowledge",
            "id": "knowledge.readme-md",
            "title": "README.md",
            "statusTag": "document",
            "statusLabel": "文档",
            "flags": ["document"],
        }
        docs = {
            "kind": "knowledge",
            "id": "knowledge.docs",
            "title": "product documentation",
            "jurisdiction": {"span": "folder"},
            "span": "folder",
            "statusLabel": "在册",
            "flags": [],
        }
        self.assertEqual("src/ag2c package  ·  一文件一张  ·  30 个文件", card_list_label("src/ag2c package", household, 30))
        self.assertEqual("src leftover parent  ·  占位", card_list_label("src leftover parent", leftover, 0))
        self.assertEqual("命令面参数解析", card_list_label("命令面参数解析", file_card, 1))
        self.assertEqual("2. 命令面参数解析", card_list_label("命令面参数解析", file_card, 1, ordinal=2))
        self.assertEqual("1-2. 命令面参数解析", card_list_label("命令面参数解析", file_card, 1, ordinal_label="1-2"))
        numbered = inspect_card({**file_card, "ordinal_label": "1-2", "summary": "命令面把参数交给 enrollment。真正的治理不在 cli.py。"}, [])
        self.assertEqual("1-2. 命令面参数解析", numbered.get("title"))
        self.assertEqual("1-2", numbered.get("ordinal"))
        self.assertNotIn("abstract", numbered)
        self.assertIn("真正的治理不在 cli.py", str(numbered.get("detail") or ""))
        self.assertEqual("README.md  ·  文档", card_list_label("README.md", readme, 0))
        self.assertEqual("product documentation  ·  整夹一张", card_list_label("product documentation", docs, 0))
        self.assertEqual("", inspect_card(file_card, [])["status"])
        self.assertEqual("占位", inspect_card(leftover, [])["status"])
        self.assertEqual("一文件一张", inspect_card(household, [])["span_label"])
        self.assertEqual("30 张文件卡", lineage_subtitle({"kind": "knowledge", "nested": True, "cards": [1], "status": "30 张文件卡"}))
        self.assertEqual("", lineage_subtitle({"kind": "knowledge", "status": "在册", "statusTag": "current"}))
        self.assertEqual("整夹一张", lineage_subtitle({"kind": "knowledge", "status": "在册", "statusTag": "current", "span": "folder", "spanLabel": "整夹一张"}))
        self.assertEqual("文档", lineage_subtitle({"kind": "knowledge", "status": "文档", "statusTag": "document"}))
        self.assertEqual("2 张知识卡", lineage_subtitle({"kind": "module", "status": "2 张知识卡", "statusTag": "current"}))

    def test_project_details_cache_skips_rebuild_until_refresh(self) -> None:
        from ag2c.management import project_details

        root = Path(tempfile.mkdtemp())
        sentinel = {"available": True, "graph": {"nodes": [{"kind": "file", "path": "app:src/a.py"}]}}
        with patch("ag2c.management.repository_root", return_value=root), patch(
            "ag2c.management.default_data_root", return_value=root / "data"
        ), patch("ag2c.management.details_fingerprint", return_value="fp-1"), patch(
            "ag2c.management._compute_project_details", return_value=sentinel
        ) as compute:
            first = project_details(root)
            second = project_details(root)
            third = project_details(root, refresh=True)
        self.assertEqual(sentinel, first)
        self.assertEqual(sentinel, second)
        self.assertEqual(sentinel, third)
        self.assertEqual(2, compute.call_count)

    def test_project_details_missing_folder_does_not_run_git(self) -> None:
        from ag2c.errors import AG2CError
        from ag2c.management import project_details

        gone = Path(tempfile.mkdtemp()) / "demo"
        with patch("ag2c.gitops.git", side_effect=AssertionError("git must not run")) as git_fn, patch(
            "ag2c.management.repository_root", side_effect=AssertionError("git must not run")
        ) as repo, patch("ag2c.management.harness_status", return_value=[]), patch(
            "ag2c.management.find_project_record", return_value={"name": "demo", "root": str(gone)}
        ):
            payload = project_details(gone)
        self.assertFalse(payload["available"])
        self.assertEqual("missing", payload["project"]["state"])
        self.assertIn("project folder is unavailable", payload["project"]["issues"])
        git_fn.assert_not_called()
        repo.assert_not_called()

        empty = Path(tempfile.mkdtemp())
        failure = AG2CError(
            "Git command failed (rev-parse --show-toplevel): fatal: cannot change to "
            f"'{empty / 'demo'}': No such file or directory"
        )
        with patch("ag2c.management.repository_root", side_effect=failure) as repo, patch(
            "ag2c.management.harness_status", return_value=[]
        ), patch("ag2c.management.find_project_record", return_value=None):
            payload = project_details(empty)
        self.assertFalse(payload["available"])
        self.assertEqual("inactive", payload["project"]["state"])
        repo.assert_called_once()

    def test_preferred_project_root_skips_missing_folders(self) -> None:
        from ag2c_gui.tray_host import preferred_project_root

        vanished = {"name": "demo", "root": r"C:\Users\Holo\AppData\Local\Temp\tmpxoioswl5\demo", "state": "missing"}
        live = {"name": "AutoGovern2Code-main", "root": r"C:\_HOLOLAB\code\AutoGovern2Code-main", "state": "protected"}
        attention = {"name": "CartridgeFlow", "root": r"C:\WorkSpace\Code\CartridgeFlow", "state": "attention"}
        self.assertEqual(live["root"], preferred_project_root([vanished, live]))
        self.assertEqual(attention["root"], preferred_project_root([vanished, live, attention]))
        self.assertEqual("", preferred_project_root([vanished]))
        self.assertEqual("", preferred_project_root([]))

    def test_load_projects_drops_a_selection_that_left_the_registry(self) -> None:
        from ag2c_gui.imgui_tray import _load_projects

        vanished = r"C:\Users\Holo\AppData\Local\Temp\tmpxoioswl5\demo"
        live = r"C:\_HOLOLAB\code\AutoGovern2Code-main"

        class State:
            def __init__(self, api, selected: str) -> None:
                self.api = api
                self.lock = threading.Lock()
                self.busy = False
                self.status = ""
                self.projects: list = []
                self.selected_root = selected

        class GoneFromRegistry:
            def request(self, method: str, path: str, body=None):
                return {"projects": [{"name": "AutoGovern2Code-main", "root": live, "state": "protected"}]}

        state = State(GoneFromRegistry(), vanished)
        _load_projects(state)
        self.assertEqual(live, state.selected_root)

        class Mixed:
            def request(self, method: str, path: str, body=None):
                return {
                    "projects": [
                        {"name": "demo", "root": vanished, "state": "missing"},
                        {"name": "AutoGovern2Code-main", "root": live, "state": "protected"},
                    ]
                }

        state = State(Mixed(), "")
        _load_projects(state)
        self.assertEqual(live, state.selected_root)

        class StillListed:
            def request(self, method: str, path: str, body=None):
                return {"projects": [{"name": "demo", "root": vanished, "state": "missing"}]}

        state = State(StillListed(), vanished)
        _load_projects(state)
        self.assertEqual(vanished, state.selected_root)

    def test_managed_projects_sorts_missing_last_and_skips_git(self) -> None:
        from ag2c import management

        management.invalidate_managed_cache()
        self.addCleanup(management.invalidate_managed_cache)
        gone = Path(tempfile.mkdtemp()) / "demo"
        live_root = Path(tempfile.mkdtemp())
        live_card = {"name": "live", "root": str(live_root), "state": "protected"}
        with patch(
            "ag2c.management.project_records",
            return_value=[
                {"name": "demo", "root": str(gone), "governance": "active"},
                {"name": "live", "root": str(live_root), "governance": "active"},
            ],
        ), patch("ag2c.management.harness_status", return_value=[]), patch(
            "ag2c.management.project_list_item", return_value=live_card
        ) as listed, patch("ag2c.management.repository_root") as repo:
            rows = management.managed_projects()
        listed.assert_called_once()
        repo.assert_not_called()
        self.assertEqual(["protected", "missing"], [row["state"] for row in rows])

    def test_managed_projects_uses_short_ttl_cache(self) -> None:
        from ag2c import management

        management.invalidate_managed_cache()
        self.addCleanup(management.invalidate_managed_cache)
        live_root = Path(tempfile.mkdtemp())
        live_card = {"name": "live", "root": str(live_root), "state": "protected"}
        with patch(
            "ag2c.management.project_records",
            return_value=[{"name": "live", "root": str(live_root), "governance": "active"}],
        ), patch("ag2c.management.harness_status", return_value=[]), patch(
            "ag2c.management.project_list_item", return_value=live_card
        ) as listed:
            management.managed_projects()
            management.managed_projects()
            # The second read inside the TTL window is served from the cache.
            self.assertEqual(listed.call_count, 1)
            management.invalidate_managed_cache()
            management.managed_projects()
            self.assertEqual(listed.call_count, 2)


class TrayGateTests(unittest.TestCase):
    def test_project_gate_rows_report_entry_delivery_records_and_anomalies(self) -> None:
        from ag2c_gui.tray_host import project_gate_rows

        project = {
            "entry_ready": True,
            "delivery_enforced": True,
            "completed_tasks": 3,
            "open_tasks": 0,
            "agents": [
                {"harness": "codex", "integrated": True, "detected": True, "state": "ready"},
                {"harness": "claude", "integrated": False, "detected": True, "state": "skill-missing"},
            ],
            "last_task": {"goal": "fix tray", "delivery": {"request": "修托盘", "outcome": "实现功能"}},
        }
        healthy = {row["id"]: row for row in project_gate_rows(project, {"worktrees": []}, mcp={"ok": True, "label": "MCP 正常"})}
        self.assertEqual("MCP 正常", healthy["gate"]["value"])
        self.assertFalse(healthy["gate"]["warn"])
        self.assertNotIn("delivery", healthy)
        self.assertIn("3 次入库", healthy["records"]["value"])
        self.assertIn("实现功能", healthy["records"]["value"])
        self.assertEqual("没有进行中的施工", healthy["worktrees"]["value"])
        self.assertFalse(healthy["worktrees"]["warn"])

        empty = {
            row["id"]: row
            for row in project_gate_rows(
                {"agents": [], "delivery_enforced": False, "completed_tasks": 0},
                None,
                mcp={"ok": False, "label": "MCP 异常"},
            )
        }
        self.assertEqual("MCP 异常", empty["gate"]["value"])
        self.assertTrue(empty["gate"]["warn"])
        self.assertNotIn("delivery", empty)
        self.assertEqual("尚未观察", empty["records"]["value"])
        unguarded = {
            row["id"]: row
            for row in project_gate_rows(
                {"delivery_enforced": False, "completed_tasks": 0},
                None,
                mcp={"ok": True, "label": "MCP 正常"},
            )
        }
        self.assertEqual("MCP 异常", unguarded["gate"]["value"])
        self.assertTrue(unguarded["gate"]["warn"])
        self.assertNotIn("delivery", unguarded)

        details = {
            "worktrees": [
                {
                    "id": "t1",
                    "state": "active",
                    "goal": "改谱系",
                    "worktree": {"lifecycle": "diverged"},
                }
            ]
        }
        sick = {row["id"]: row for row in project_gate_rows(project, details)}
        self.assertTrue(sick["worktrees"]["warn"])
        self.assertIn("已分叉", sick["worktrees"]["value"])

    def test_lineage_mark_matches_card_id_and_module_copy(self) -> None:
        from ag2c_gui.imgui_tray import _lineage_is_marked

        node = {"kind": "knowledge", "id": "knowledge.src", "visual_id": "knowledge.src@module:config", "title": "config exploring household"}
        self.assertTrue(_lineage_is_marked(node, "knowledge.src", set(), ""))
        self.assertTrue(_lineage_is_marked(node, "", {"knowledge.src"}, ""))
        self.assertTrue(_lineage_is_marked(node, "", set(), "knowledge.src@module:config"))
        self.assertTrue(_lineage_is_marked(node, "config exploring household", set(), ""))
        self.assertFalse(_lineage_is_marked(node, "other", set(), "module:src"))


class TrayAuditTests(unittest.TestCase):
    def test_audit_records_clicks_to_ring_and_log_file(self) -> None:
        from ag2c_gui.imgui_tray import AUDIT_LIMIT, AppState, audit

        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "ag2c-audit.log"
            with patch.dict(os.environ, {"AG2C_AUDIT_LOG": str(log)}):
                state = AppState([])
                audit(state, "点击文件", "文件树", "src/ag2c/imgui_tray.py")
                audit(state, "点击知识卡", "知识卡片", "源码治理")
                audit(state, "展开", "谱系", "module:src/ag2c")
                written = log.read_text(encoding="utf-8")
            self.assertEqual(3, len(state.audit_lines))
            self.assertIn("点击文件", state.audit_lines[0])
            self.assertIn("文件树", state.audit_lines[0])
            self.assertIn("src/ag2c/imgui_tray.py", state.audit_lines[0])
            self.assertIn("知识卡片", state.audit_lines[1])
            self.assertIn("源码治理", state.audit_lines[1])
            self.assertIn("展开  谱系  module:src/ag2c", state.audit_lines[2])
            self.assertIn("点击文件  文件树  src/ag2c/imgui_tray.py", written)
            self.assertIn("点击知识卡  知识卡片  源码治理", written)
            self.assertIn("展开  谱系  module:src/ag2c", written)
        self.assertGreaterEqual(AUDIT_LIMIT, 100)

    def test_audit_ring_drops_oldest_past_limit(self) -> None:
        from ag2c_gui.imgui_tray import AUDIT_LIMIT, AppState, audit

        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "ag2c-audit.log"
            with patch.dict(os.environ, {"AG2C_AUDIT_LOG": str(log)}):
                state = AppState([])
                for index in range(AUDIT_LIMIT + 25):
                    audit(state, "点击", "测试", str(index))
            self.assertEqual(AUDIT_LIMIT, len(state.audit_lines))
            self.assertTrue(state.audit_lines[0].endswith(" 测试  25"))
            self.assertTrue(state.audit_lines[-1].endswith(f" 测试  {AUDIT_LIMIT + 24}"))
            joined = "\n".join(state.audit_lines) + "\n"
            self.assertNotIn(" 测试  0\n", joined)
            self.assertNotIn(" 测试  24\n", joined)

    def test_focus_path_and_card_write_audit_lines(self) -> None:
        from ag2c_gui.imgui_tray import AppState, _focus_card, _focus_path

        tray = {
            "kind": "file",
            "id": "file:app:src/ag2c/imgui_tray.py",
            "title": "imgui_tray.py",
            "path": "app:src/ag2c/imgui_tray.py",
            "coveredBy": ["源码治理"],
        }
        card = {
            "kind": "knowledge",
            "id": "knowledge.src",
            "title": "源码治理",
            "summary": "对照",
            "flags": [],
        }
        details = {"graph": {"nodes": [tray, card]}, "cards": [card], "project": {"name": "AutoGovern2Code"}}
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "ag2c-audit.log"
            with patch.dict(os.environ, {"AG2C_AUDIT_LOG": str(log)}):
                state = AppState([])
                state.details = details
                _focus_path(state, "src/ag2c/imgui_tray.py")
                self.assertEqual("src/ag2c/imgui_tray.py", state.selected_file)
                _focus_card(state, card)
                self.assertEqual("knowledge.src", state.selected_card_key)
                _focus_path(state, "missing/nope.py", where="详情")
                written = log.read_text(encoding="utf-8")
            actions = [line.split("  ", 3)[1] for line in state.audit_lines]
            self.assertIn("点击文件", state.audit_lines[0])
            self.assertIn("文件树", state.audit_lines[0])
            self.assertIn("src/ag2c/imgui_tray.py", state.audit_lines[0])
            self.assertIn("点击知识卡", state.audit_lines[1])
            self.assertIn("知识卡片", state.audit_lines[1])
            self.assertIn("源码治理", state.audit_lines[1])
            self.assertIn("未命中文件", state.audit_lines[-1])
            self.assertIn("详情", state.audit_lines[-1])
            self.assertIn("missing/nope.py", state.audit_lines[-1])
            self.assertEqual(["点击文件", "点击知识卡", "点击文件", "未命中文件"], actions)
            self.assertIn("未命中文件  详情  missing/nope.py", written)

    def test_audit_overlay_is_not_a_dock_and_newest_is_reversed_in_gui_source(self) -> None:
        ui = (Path(__file__).resolve().parents[1] / "src" / "ag2c_gui" / "imgui_tray.py").read_text(encoding="utf-8")
        self.assertIn("reversed(state.audit_lines)", ui)
        self.assertIn('small_button("清空")', ui)
        self.assertIn('small_button("打开日志文件")', ui)
        self.assertIn("还没有操作。点击文件、知识卡或谱系节点后会出现在这里。", ui)
        self.assertIn("点击谱系节点", ui)
        self.assertIn('audit(state, "展开" if opening else "收起", "谱系", visual_id)', ui)
        self.assertIn('audit(state, "点击目录", "文件树", prefix)', ui)
        windows_block = ui[ui.index("def _windows"): ui.index("def _gui_splash")]
        self.assertNotIn("审计", windows_block)


class HiddenConsoleTests(unittest.TestCase):
    def test_hidden_process_kwargs_hide_windows_consoles(self) -> None:
        from ag2c.util import hidden_process_kwargs

        kwargs = hidden_process_kwargs()
        if os.name != "nt":
            self.assertEqual({}, kwargs)
            return
        self.assertEqual(subprocess.CREATE_NO_WINDOW, kwargs["creationflags"])
        self.assertTrue(kwargs["startupinfo"].dwFlags & subprocess.STARTF_USESHOWWINDOW)
        self.assertEqual(0, kwargs["startupinfo"].wShowWindow)

    def test_git_index_and_checks_pass_hidden_console_flags(self) -> None:
        from ag2c.gitops import _run_git
        from ag2c.index import _git
        from ag2c.util import hidden_process_kwargs

        hidden = hidden_process_kwargs()
        completed = MagicMock(returncode=0, stdout="ok", stderr="")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("ag2c.gitops.subprocess.run", return_value=completed) as git_run:
                _run_git("git", root, "status", check=False)
            with patch("ag2c.index.git_executable", return_value="git"), patch(
                "ag2c.index.subprocess.run", return_value=completed
            ) as index_run:
                _git(root, "rev-parse", "HEAD")
        for mocked in (git_run, index_run):
            kwargs = mocked.call_args.kwargs
            if os.name == "nt":
                self.assertEqual(hidden["creationflags"], kwargs["creationflags"])
                self.assertTrue(kwargs["startupinfo"].dwFlags & subprocess.STARTF_USESHOWWINDOW)
            else:
                self.assertNotIn("creationflags", kwargs)

    def test_runtime_and_desktop_server_do_not_open_a_console(self) -> None:
        from ag2c_gui.tray_host import runtime_command, start_desktop_server

        command = runtime_command([], Path("."))
        self.assertEqual("-m", command[1])
        self.assertEqual("ag2c", command[2])
        if os.name == "nt":
            pythonw = Path(sys.executable).with_name("pythonw.exe")
            if Path(sys.executable).name.lower() == "python.exe" and pythonw.is_file():
                self.assertEqual(str(pythonw), command[0])
        with patch("subprocess.Popen") as popped:
            start_desktop_server(command, 9, "token-token-token-token-token")
        kwargs = popped.call_args.kwargs
        if os.name == "nt":
            self.assertEqual(subprocess.CREATE_NO_WINDOW, kwargs["creationflags"])
            self.assertTrue(kwargs["startupinfo"].dwFlags & subprocess.STARTF_USESHOWWINDOW)

    def test_checker_runner_hides_console_windows(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "src" / "ag2c" / "checks.py").read_text(encoding="utf-8")
        self.assertIn("**hidden_process_kwargs()", source)

    def test_wait_for_status_can_be_cancelled(self) -> None:
        from ag2c_gui.tray_host import wait_for_status

        class DeadApi:
            def request(self, *args: object, **kwargs: object) -> dict[str, str]:
                raise ConnectionError("down")

        started = time.perf_counter()
        self.assertFalse(wait_for_status(DeadApi(), attempts=20, pause=0.05, cancelled=lambda: True))
        self.assertLess(time.perf_counter() - started, 0.2)


if __name__ == "__main__":
    unittest.main()
