from __future__ import annotations

import http.client
import json
import socket
import sys
import threading
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import bootstrap

import ag2c.desktop
from ag2c.desktop import DesktopServer


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
        with patch("ag2c.desktop.managed_projects", return_value=[{"name": "Project", "root": "C:/Project"}]) as listed, patch(
            "ag2c.desktop.align_managed_projects"
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
        with patch("ag2c.desktop.add_project", return_value=expected) as add:
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
        with patch("ag2c.desktop.align_managed_projects", return_value=[{"action": "aligned"}]) as align, patch(
            "ag2c.desktop.managed_projects", return_value=[{"name": "Project", "root": "C:/Project"}]
        ):
            status, body, _ = self.request("POST", "/api/projects/align", body={}, token=True)
        self.assertEqual(200, status)
        payload = json.loads(body)
        self.assertEqual([{"action": "aligned"}], payload["migrations"])
        self.assertEqual("Project", payload["projects"][0]["name"])
        align.assert_called_once()

    def test_recheck_repairs_activation_before_returning_status(self) -> None:
        expected = {"name": "Project", "root": "C:/Project", "state": "protected"}
        with patch("ag2c.desktop.repair_and_check_project", return_value=expected) as repair:
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
        with patch("ag2c.desktop.project_details", return_value=expected) as details:
            status, body, _ = self.request(
                "POST",
                "/api/project/details",
                body={"path": "C:/Project"},
                token=True,
            )
        self.assertEqual(200, status)
        self.assertEqual(expected, json.loads(body))
        details.assert_called_once()

    def test_serve_desktop_notifies_after_socket_is_bound(self) -> None:
        from ag2c.desktop import serve_desktop

        ready = []

        def stop(port: int) -> None:
            ready.append(port)

        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        with patch("ag2c.desktop.DesktopServer.serve_forever", side_effect=KeyboardInterrupt):
            self.assertEqual(
                0,
                serve_desktop(port=port, token="test-token-with-at-least-24-characters", on_ready=stop),
            )
        self.assertEqual(1, len(ready))
        self.assertGreater(ready[0], 0)


class TrayHostSourceTests(unittest.TestCase):
    def test_tray_host_is_hello_imgui_without_webview2_or_pyside(self) -> None:
        root = Path(__file__).resolve().parents[1]
        ui = (root / "src" / "ag2c" / "imgui_tray.py").read_text(encoding="utf-8")
        host = (root / "src" / "ag2c" / "tray_host.py").read_text(encoding="utf-8")
        entry = (root / "packaging" / "windows" / "tray.py").read_text(encoding="utf-8")
        build = (root / "scripts" / "build_windows_installer.ps1").read_text(encoding="utf-8")
        installer = (root / "packaging" / "windows" / "AutoGovern2Code.iss").read_text(encoding="utf-8")
        self.assertIn("from imgui_bundle import hello_imgui", ui)
        self.assertIn("DockableWindow", ui)
        self.assertIn("portable_file_dialogs", ui)
        self.assertIn("from ag2c.imgui_tray import main", entry)
        self.assertIn("packaging\\windows\\tray.py", build)
        self.assertIn("NOTICE-imgui.txt", build)
        self.assertIn("tray-host", installer)
        self.assertIn("--portable", host)
        self.assertIn("portable.ini", host)
        launcher = (root / "start-tray.bat").read_text(encoding="utf-8")
        self.assertIn("packaging\\windows\\tray.py", launcher)
        self.assertIn("imgui-bundle", launcher)
        self.assertIn("pythonw.exe", launcher)
        self.assertFalse((root / "src" / "ag2c" / "qt_tray.py").exists())
        self.assertFalse((root / "src" / "ag2c" / "ui").exists())
        self.assertFalse((root / "start-governance-viewer.cmd").exists())
        self.assertFalse((root / "打开管理界面.bat").exists())


class TrayFontTests(unittest.TestCase):
    def test_windows_cjk_font_file_exists(self) -> None:
        from ag2c.imgui_tray import cjk_font_path

        found = cjk_font_path()
        self.assertIsNotNone(found)
        assert found is not None
        self.assertTrue(found.is_file())
        self.assertEqual("C:\\Windows\\Fonts", str(found.parent))

    def test_load_fonts_uses_filesystem_cjk_as_default(self) -> None:
        from ag2c.imgui_tray import _load_fonts, cjk_font_path

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
        from ag2c.imgui_tray import node_key, widget_id

        label = "ADOPTION.md  ·  在册"
        left = widget_id(label, node_key({"title": "ADOPTION.md", "path": "docs/ADOPTION.md"}))
        right = widget_id(label, node_key({"title": "ADOPTION.md", "path": "docs/zh-CN/ADOPTION.md"}))
        self.assertNotEqual(left, right)
        self.assertTrue(left.startswith(label))
        self.assertIn("docs/ADOPTION.md", left)
        self.assertIn("docs/zh-CN/ADOPTION.md", right)

    def test_tray_hides_nav_cursor_and_uses_unique_selectable_ids(self) -> None:
        ui = (Path(__file__).resolve().parents[1] / "src" / "ag2c" / "imgui_tray.py").read_text(encoding="utf-8")
        self.assertIn("set_nav_cursor_visible(False)", ui)
        self.assertIn("Col_.nav_cursor", ui)
        self.assertIn("widget_id(label, root)", ui)
        self.assertIn("widget_id(label, key)", ui)
        self.assertIn("inspect_key", ui)


class TrayHostHelperTests(unittest.TestCase):
    def test_coverage_filter_keeps_exploring_cards(self) -> None:
        from ag2c.tray_host import coverage_rows, node_matches

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


if __name__ == "__main__":
    unittest.main()
