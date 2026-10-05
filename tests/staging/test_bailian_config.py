"""Credential import failures must not leak content or overwrite local config."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "bailian_config_test", ROOT / "scripts/staging/configure-bailian-ocr.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BailianConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()
        self.fake_value = "sk-" + "synthetic" * 4

    def test_clipboard_import_does_not_echo_value(self) -> None:
        output = io.StringIO()
        response = subprocess.CompletedProcess(["pbpaste"], 0, (self.fake_value + "\n").encode())
        with patch.object(self.module.subprocess, "run", return_value=response), contextlib.redirect_stdout(output):
            imported = self.module._clipboard_key()
        self.assertEqual(imported, self.fake_value)
        self.assertNotIn(self.fake_value, output.getvalue())

    def test_workspace_key_format_is_accepted(self) -> None:
        self.assertTrue(self.module._valid_key("sk-ws-" + "a" * 24))

    def test_unrelated_clipboard_is_rejected_without_content_in_error(self) -> None:
        response = subprocess.CompletedProcess(["pbpaste"], 0, b"unrelated private clipboard content")
        with patch.object(self.module.subprocess, "run", return_value=response), self.assertRaises(SystemExit) as caught:
            self.module._clipboard_key()
        self.assertNotIn("private clipboard content", str(caught.exception))

    def test_dialog_cancellation_has_no_traceback_or_config_write(self) -> None:
        with patch.object(self.module.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "osascript")), self.assertRaises(SystemExit) as caught:
            self.module._dialog_key()
        self.assertIn("configuration was not changed", str(caught.exception))

    def test_dialog_import_preserves_other_config_and_writes_owner_only_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".env.staging"
            path.write_text("UNRELATED=preserve\nSTAGING_DATA_CLASSIFICATION=synthetic\n", encoding="utf-8")
            output = io.StringIO()
            arguments = ["configure", "--region", "us-east-1", "--workspace-id", "workspace-test", "--env-file", str(path), "--key-from-dialog"]
            with patch("sys.argv", arguments), patch.object(self.module, "_dialog_key", return_value=self.fake_value), contextlib.redirect_stdout(output):
                self.assertEqual(self.module.main(), 0)
            self.assertNotIn(self.fake_value, output.getvalue())
            values = self.module._read_values(path)
            self.assertEqual(values["DASHSCOPE_API_KEY"], self.fake_value)
            self.assertEqual(values["UNRELATED"], "preserve")
            self.assertEqual(values["STAGING_DATA_CLASSIFICATION"], "synthetic")
            self.assertEqual(values["OCR_PROVIDER"], "qwen-vl-ocr")
            self.assertEqual(values["DASHSCOPE_MODEL"], "qwen-vl-ocr")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(list(path.parent.glob(".env.staging-*")), [])

    def test_invalid_key_leaves_existing_file_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".env.staging"
            original = "OCR_PROVIDER=fixture\n"
            path.write_text(original, encoding="utf-8")
            arguments = ["configure", "--region", "us-east-1", "--workspace-id", "workspace-test", "--env-file", str(path), "--key-from-dialog"]
            with patch("sys.argv", arguments), patch.object(self.module, "_dialog_key", return_value="not a key"), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                self.module.main()
            self.assertEqual(path.read_text(), original)

    def test_git_tracked_destination_is_rejected(self) -> None:
        with self.assertRaises(SystemExit):
            self.module._check_destination(ROOT / "README.md")


if __name__ == "__main__":
    unittest.main()
