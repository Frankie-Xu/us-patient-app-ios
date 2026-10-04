#!/usr/bin/env python3
"""Create a redacted, deterministic release evidence manifest.

The manifest contains statuses and run metadata only. Command output, paths,
request data, PHI and credentials are captured in memory and never serialized.
Use --from-ci in the aggregate workflow after the component jobs finish.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "patient-app-platform/release-evidence"
SCHEMA_VERSION = "1.0.0"
_ALLOWED_RESULT = {"success", "failure", "cancelled", "skipped", "neutral"}
_SAFE_META = re.compile(r"^[A-Za-z0-9._@ -]{1,100}$")
_SAFE_SHA = re.compile(r"^[0-9a-f]{7,64}$")


class EvidenceError(RuntimeError):
    pass


def _safe(value: str | None, *, default: str) -> str:
    if value is None or not _SAFE_META.fullmatch(value):
        return default
    return value


def _commit(repo_root: Path) -> str:
    supplied = os.environ.get("GITHUB_SHA")
    if supplied and _SAFE_SHA.fullmatch(supplied):
        return supplied
    try:
        value = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_root, check=True,
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return value if _SAFE_SHA.fullmatch(value) else "unknown"


def _metadata(repo_root: Path) -> dict[str, Any]:
    return {
        "commit_sha": _commit(repo_root),
        "workflow_name": _safe(os.environ.get("GITHUB_WORKFLOW"), default="local"),
        "workflow_version": _safe(os.environ.get("RELEASE_EVIDENCE_WORKFLOW_VERSION"), default="local"),
        "run_id": _safe(os.environ.get("GITHUB_RUN_ID"), default="local"),
        "run_number": _safe(os.environ.get("GITHUB_RUN_NUMBER"), default="local"),
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }


def _status(result: str) -> str:
    if result == "success":
        return "passed"
    if result == "skipped":
        return "skipped"
    return "failed"


def _from_ci() -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for group in ("repository", "contract", "api", "ai", "ios"):
        raw = os.environ.get(f"RELEASE_EVIDENCE_{group.upper()}_RESULT")
        result = raw if raw in _ALLOWED_RESULT else "failure"
        groups[group] = {
            "status": _status(result),
            "checks": [{"id": f"{group}.ci_job", "status": _status(result), "exit_code": 0 if result in {"success", "skipped", "neutral"} else 1}],
        }
    return groups


def _run(repo_root: Path, group: str, commands: list[tuple[str, list[str]]]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    for check_id, command in commands:
        started = time.monotonic()
        status, exit_code = "passed", 0
        try:
            result = subprocess.run(
                command, cwd=repo_root, capture_output=True, text=True,
                timeout=1800 if group == "ios" else 600, check=False,
            )
            exit_code = result.returncode
            status = "passed" if exit_code == 0 else "failed"
        except (OSError, subprocess.SubprocessError):
            status, exit_code = "failed", 1
        checks.append({"id": check_id, "status": status, "exit_code": exit_code, "duration_ms": int((time.monotonic() - started) * 1000)})
    return {"status": "passed" if all(item["status"] == "passed" for item in checks) else "failed", "checks": checks}


def _local(repo_root: Path) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {
        "repository": _run(repo_root, "repository", [
            ("repository.validation", ["bash", "scripts/validate-repo.sh"]),
            ("repository.dependencies", ["bash", "scripts/check-dependencies.sh"]),
            ("repository.workflow_pins", ["bash", "scripts/check-workflow-pins.sh"]),
            ("repository.scanner_regression", ["bash", "scripts/test-validate-repo.sh"]),
            ("repository.patch_format", ["git", "diff", "--check"]),
        ]),
        "contract": _run(repo_root, "contract", [("contract.openapi", ["bash", "scripts/check-openapi.sh"])]),
        "api": _run(repo_root, "api", [
            ("api.readiness", ["bash", "scripts/run-api-readiness.sh", "services/api"]),
            ("api.tests", ["bash", "scripts/run-python-tests.sh", "services/api"]),
        ]),
        "ai": _run(repo_root, "ai", [
            ("ai.golden_regression", ["bash", "scripts/run-ai-golden-regression.sh", "services/ai"]),
            ("ai.tests", ["bash", "scripts/run-python-tests.sh", "services/ai"]),
        ]),
    }
    ios_markers = ("Package.swift", "project.pbxproj", "contents.xcworkspacedata")
    ios_root = repo_root / "apps/ios"
    ios_present = any(next(ios_root.rglob(marker), None) is not None for marker in ios_markers)
    groups["ios"] = _run(repo_root, "ios", [("ios.tests", ["bash", "scripts/run-ios-tests.sh", "apps/ios"])]) if ios_present else {"status": "skipped", "checks": [{"id": "ios.tests", "status": "skipped", "exit_code": 0}]}
    return groups


def _manifest(repo_root: Path, groups: dict[str, dict[str, Any]]) -> dict[str, Any]:
    failed = sorted(group for group, value in groups.items() if value["status"] == "failed")
    statuses = [value["status"] for value in groups.values()]
    return {
        "manifest_schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "metadata": _metadata(repo_root),
        "checks": groups,
        "overall": {
            "status": "failed" if failed else "passed",
            "failed_groups": failed,
            "passed_groups": sum(value == "passed" for value in statuses),
            "skipped_groups": sum(value == "skipped" for value in statuses),
            "total_groups": len(groups),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="artifacts/release-evidence.json")
    parser.add_argument("--from-ci", action="store_true", help="consume sanitized component job results")
    args = parser.parse_args(argv)
    repo_root = Path(os.environ.get("VALIDATION_ROOT", Path(__file__).resolve().parents[1])).resolve()
    groups = _from_ci() if args.from_ci else _local(repo_root)
    manifest = _manifest(repo_root, groups)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    return 0 if manifest["overall"]["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
