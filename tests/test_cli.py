from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import bootstrap

from ag2c.cli import main


class CLITests(unittest.TestCase):
    def test_browser_viewer_command_is_removed(self) -> None:
        output = io.StringIO()
        with patch("ag2c.desktop.serve_desktop") as serve, redirect_stdout(output):
            with self.assertRaises(SystemExit):
                main(["viewer", "--open"])
        serve.assert_not_called()

    def test_project_uninstall_removes_governance_data(self) -> None:
        output = io.StringIO()
        with patch("ag2c.management.stop_managing", return_value={"uninstalled": True, "data_removed": True}) as stop, redirect_stdout(output):
            self.assertEqual(0, main(["project", "uninstall", "C:/tmp/project"]))
        stop.assert_called_once()
        self.assertTrue(stop.call_args.kwargs["remove_data"])
