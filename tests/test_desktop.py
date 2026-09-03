from __future__ import annotations

import http.client
import json
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_static_ui_and_status_are_local_desktop_assets(self) -> None:
        status, body, headers = self.request("GET", "/")
        self.assertEqual(200, status)
        self.assertIn(b"AutoGovern2Code", body)
        self.assertIn("施工副本".encode("utf-8"), body)
        self.assertIn("待更新规则".encode("utf-8"), body)
        self.assertIn("治理日志".encode("utf-8"), body)
        self.assertIn(b"listDialog", body)
        self.assertIn(b"busyOverlay", body)
        self.assertIn(b"gateObservedToggle", body)
        self.assertIn("卸载项目".encode("utf-8"), body)
        status, script, _ = self.request("GET", "/assets/app.js")
        self.assertEqual(200, status)
        self.assertIn(b"function yesNo", script)
        self.assertIn(b"function setBusy", script)
        self.assertIn(b"function deliveryKindName", script)
        self.assertIn(b"function addProjectError", script)
        self.assertIn(b"function fillEvidenceList", script)
        self.assertIn("verify_local=False", Path(ag2c.desktop.__file__).read_text(encoding="utf-8"))
        self.assertIn("正在读取实际记录".encode("utf-8"), script)
        self.assertIn(b"AG2C_STALE_EXTERNAL_STORE", script)
        self.assertIn(b"AG2C_RELOCATED_PROJECT", script)
        self.assertIn("查看全部".encode("utf-8"), script)
        self.assertIn(b"function isDesktopHost", script)
        self.assertIn(b"ag2cSetDesktopHost", script)
        self.assertIn(b"ag2c://choose-project", script)
        self.assertIn(b"alignAndRefresh", script)
        self.assertIn(b"/api/projects/revision", script)
        self.assertIn(b"keepPainted", script)
        self.assertIn("产品验收".encode("utf-8"), script)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        status, body, headers = self.request("GET", "/api/status")
        self.assertEqual(200, status)
        self.assertTrue(headers["X-AG2C-Desktop"].startswith("desktop/"))
        capabilities = json.loads(body)["capabilities"]
        self.assertIn("web-folder-picker", capabilities)
        self.assertIn("native-folder-picker", capabilities)

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
        self.assertEqual([], payload["migrations"])
        self.assertIn("version", payload)
        listed.assert_called_once()
        align.assert_not_called()

    def test_session_endpoint_returns_current_token_for_local_tabs(self) -> None:
        status, body, _ = self.request("GET", "/api/session", origin="http://127.0.0.1")
        self.assertEqual(200, status)
        self.assertEqual("test-token-with-at-least-24-characters", json.loads(body)["token"])
        status, body, _ = self.request("GET", "/api/session")
        self.assertEqual(200, status)
        self.assertEqual("test-token-with-at-least-24-characters", json.loads(body)["token"])

    def test_page_cookie_authorizes_later_project_requests(self) -> None:
        status, _, headers = self.request("GET", "/")
        self.assertEqual(200, status)
        cookie = headers.get("Set-Cookie", "")
        self.assertIn("ag2c-token=test-token-with-at-least-24-characters", cookie)
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        with patch("ag2c.desktop.managed_projects", return_value=[{"name": "Project", "root": "C:/Project"}]):
            connection.request(
                "GET",
                "/api/projects",
                headers={
                    "Host": f"127.0.0.1:{self.port}",
                    "Cookie": "ag2c-token=test-token-with-at-least-24-characters",
                },
            )
            response = connection.getresponse()
            body = response.read()
            connection.close()
        self.assertEqual(200, response.status)
        self.assertEqual("Project", json.loads(body)["projects"][0]["name"])

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

    def test_filesystem_endpoint_returns_browsable_folders(self) -> None:
        expected = {
            "path": "C:/Project",
            "parent": "C:/",
            "is_git": True,
            "directories": [{"name": "src", "path": "C:/Project/src", "is_git": False}],
            "truncated": False,
        }
        with patch("ag2c.desktop.list_project_folders", return_value=expected) as list_folders:
            status, body, _ = self.request(
                "POST",
                "/api/filesystem/list",
                body={"path": "C:/Project"},
                token=True,
            )
        self.assertEqual(200, status)
        self.assertEqual(expected, json.loads(body))
        list_folders.assert_called_once_with(Path("C:/Project"))

    def test_describe_picked_folder_marks_git_and_cancel(self) -> None:
        from ag2c.desktop import describe_picked_folder
        from ag2c.errors import AG2CError

        self.assertEqual(
            {"cancelled": True, "unavailable": False, "path": None, "is_git": False},
            describe_picked_folder(None),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            selected = describe_picked_folder(root)
            self.assertFalse(selected["cancelled"])
            self.assertFalse(selected["unavailable"])
            self.assertTrue(selected["is_git"])
            self.assertEqual(str(root.resolve()), selected["path"])
            missing = root / "missing"
            with self.assertRaisesRegex(AG2CError, "folder is unavailable"):
                describe_picked_folder(missing)

    def test_filesystem_pick_endpoint_returns_native_selection(self) -> None:
        expected = {"cancelled": False, "unavailable": False, "path": "C:/Project", "is_git": True}
        with patch("ag2c.desktop.pick_project_folder", return_value=expected) as pick:
            status, body, _ = self.request("POST", "/api/filesystem/pick", body={}, token=True)
        self.assertEqual(200, status)
        self.assertEqual(expected, json.loads(body))
        pick.assert_called_once_with()

    def test_pick_project_folder_treats_dismissed_dialog_as_cancel(self) -> None:
        from ag2c.desktop import pick_project_folder

        with patch("ag2c.desktop._native_folder_path", return_value=None):
            self.assertEqual(
                {"cancelled": True, "unavailable": False, "path": None, "is_git": False},
                pick_project_folder(),
            )
        with patch("ag2c.desktop._native_folder_path", side_effect=RuntimeError("no display")):
            self.assertEqual(
                {"cancelled": False, "unavailable": True, "path": None, "is_git": False},
                pick_project_folder(),
            )
        from ag2c.desktop import _PickerCancelled, _windows_dialog_cancelled, _windows_show_result

        with patch("ag2c.desktop._native_folder_path", side_effect=_PickerCancelled()):
            self.assertEqual(
                {"cancelled": True, "unavailable": False, "path": None, "is_git": False},
                pick_project_folder(),
            )
        self.assertTrue(_windows_dialog_cancelled(0x800704C7))
        self.assertTrue(_windows_dialog_cancelled(0x80004004))
        self.assertTrue(_windows_dialog_cancelled(1223))
        self.assertFalse(_windows_dialog_cancelled(0))
        _windows_show_result(0)
        with self.assertRaises(_PickerCancelled):
            _windows_show_result(0x800704C7)
        with self.assertRaises(_PickerCancelled):
            _windows_show_result(0x80004004)

    def test_list_project_folders_marks_git_directories(self) -> None:
        from ag2c.desktop import list_project_folders

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "repository"
            (repository / ".git").mkdir(parents=True)
            (root / "plain").mkdir()
            (root / "file.txt").write_text("ignored", encoding="utf-8")
            result = list_project_folders(root)

        directories = {item["name"]: item for item in result["directories"]}
        self.assertEqual(str(root.resolve()), result["path"])
        self.assertTrue(directories["repository"]["is_git"])
        self.assertFalse(directories["plain"]["is_git"])
        self.assertNotIn("file.txt", directories)

    def test_projects_revision_endpoint_is_available(self) -> None:
        with patch("ag2c.desktop.projects_revision", return_value={"revision": "abc123"}) as revision:
            status, body, _ = self.request("GET", "/api/projects/revision", token=True)
        self.assertEqual(200, status)
        self.assertEqual("abc123", json.loads(body)["revision"])
        revision.assert_called_once()

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


if __name__ == "__main__":
    unittest.main()
