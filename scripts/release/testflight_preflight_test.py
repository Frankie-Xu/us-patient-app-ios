#!/usr/bin/env python3
from __future__ import annotations

import json
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("testflight_preflight.py")


class TestFlightPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "evidence"
        self.root.mkdir()
        self._write_plist(
            self.root / "Payload/Patient.app/Info.plist",
            {"CFBundleShortVersionString": "1.4.0", "CFBundleVersion": "42"},
        )
        self._write_json(
            self.root / "Config/build-settings.json",
            {
                "configuration": "Release",
                "CODE_SIGN_STYLE": "Automatic",
                "DEVELOPMENT_TEAM": "TEAM_ID_PLACEHOLDER",
            },
        )
        for locale in ("en", "zh-Hans"):
            path = self.root / f"Payload/Patient.app/{locale}.lproj/Localizable.strings"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('"status.loading.title" = "Loading";\n', encoding="utf-8")
        dsym = self.root / "dSYMs/Patient.app.dSYM/Contents/Resources/DWARF/Patient"
        dsym.parent.mkdir(parents=True, exist_ok=True)
        dsym.write_bytes(b"synthetic symbol table")
        self._write_json(self.root / "crash-monitoring.json", {"provider": "sentry", "dsn": "DSN_PLACEHOLDER"})

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @staticmethod
    def _write_json(path: Path, value: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    @staticmethod
    def _write_plist(path: Path, value: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(plistlib.dumps(value))

    def _run(self, *extra: str) -> tuple[int, dict[str, object], str]:
        output = self.root.parent / "report.json"
        command = [sys.executable, str(SCRIPT), "--evidence-dir", str(self.root), "--output", str(output), *extra]
        result = subprocess.run(command, check=False, capture_output=True, text=True)
        return result.returncode, json.loads(output.read_text(encoding="utf-8")), result.stdout

    def test_dry_run_passes_without_credentials(self) -> None:
        status, report, stdout = self._run("--dry-run")
        self.assertEqual(status, 0)
        self.assertEqual(report["overall"]["status"], "passed")
        self.assertEqual(report["mode"], "dry-run")
        self.assertEqual(stdout.strip(), "testflight preflight: passed")

    def test_report_is_deterministic(self) -> None:
        first_status, first, _ = self._run("--dry-run")
        second_status, second, _ = self._run("--dry-run")
        self.assertEqual(first_status, second_status)
        self.assertEqual(first, second)

    def test_missing_items_are_classified_and_fail(self) -> None:
        (self.root / "Payload/Patient.app/zh-Hans.lproj/Localizable.strings").unlink()
        for path in (self.root / "dSYMs").rglob("*"):
            if path.is_file():
                path.unlink()
        (self.root / "crash-monitoring.json").unlink()
        status, report, _ = self._run("--dry-run")
        self.assertEqual(status, 1)
        self.assertEqual(
            set(report["overall"]["failed_categories"]),
            {"resources", "symbols", "crash_monitoring"},
        )
        self.assertEqual(
            {item["category"] for item in report["missing_items"]},
            {"resources", "symbols", "crash_monitoring"},
        )

    def test_invalid_build_fails(self) -> None:
        self._write_plist(
            self.root / "Payload/Patient.app/Info.plist",
            {"CFBundleShortVersionString": "1.4.0", "CFBundleVersion": "build-secret"},
        )
        status, report, _ = self._run("--dry-run")
        self.assertEqual(status, 1)
        self.assertEqual(report["checks"]["version"]["code"], "invalid_build_number")

    def test_credential_like_content_is_redacted(self) -> None:
        secret = "-----BEGIN " + "PRIVATE KEY-----\nPRIVATE_CONTENT_SHOULD_NOT_PRINT\n-----END " + "PRIVATE KEY-----"
        (self.root / "Config/accidental-secret.txt").write_text(secret, encoding="utf-8")
        status, report, stdout = self._run("--dry-run")
        self.assertEqual(status, 1)
        self.assertEqual(report["checks"]["credential_hygiene"]["code"], "credential_like_content_detected")
        serialized = json.dumps(report)
        self.assertNotIn("PRIVATE_CONTENT_SHOULD_NOT_PRINT", serialized)
        self.assertNotIn("PRIVATE_CONTENT_SHOULD_NOT_PRINT", stdout)


if __name__ == "__main__":
    unittest.main()
