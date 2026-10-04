#!/usr/bin/env python3
"""Validate that release evidence is aggregate and free of sensitive material.

This is an offline check over generated JSON manifests.  It intentionally emits
only fixed violation codes and counts; no input path, value, PHI or token is
included in diagnostics or the output manifest.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

SCHEMA = "patient-app-platform/privacy-evidence"
VERSION = "1.0.0"
ALLOWED_INPUT_SCHEMAS = {
    "patient-app-platform/release-evidence",
    "patient-app-platform/production-gate",
}
SENSITIVE_KEY = re.compile(
    r"(?:authorization|access[_-]?token|refresh[_-]?token|secret|credential|password|cookie|private[_-]?key|request[_-]?body|response[_-]?body|stdout|stderr|command|filename|file[_-]?path|(?:^|[_-])path$|patient(?:[_ -]?name)?|diagnosis|medical[_ -]?record|social[_ -]?security|date[_ -]?of[_ -]?birth|\bphi\b)",
    re.IGNORECASE,
)
SENSITIVE_VALUE = re.compile(
    r"(?:-----BEGIN [A-Z ]+PRIVATE KEY-----|(?:^|\s)Bearer\s+\S+|(?:^|\s)(?:sk|ghp)_[A-Za-z0-9]{12,}|(?:^|[\\/])(?:Users|home|private|tmp|workspace|var)[\\/]|\b(?:patient\s+name|medical\s+record|diagnosis|social\s+security|date\s+of\s+birth)\b|[?&](?:access[_-]?token|refresh[_-]?token|api[_-]?key|client[_-]?secret|token)=[^&#\s]{8,})",
    re.IGNORECASE,
)


def _root() -> Path:
    return Path(os.environ.get("VALIDATION_ROOT", Path(__file__).resolve().parents[1])).resolve()


def _walk(value: Any, violations: set[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key != "production_phi_allowed" and SENSITIVE_KEY.search(str(key)):
                violations.add("sensitive_key")
            _walk(child, violations)
    elif isinstance(value, list):
        for child in value:
            _walk(child, violations)
    elif isinstance(value, str) and SENSITIVE_VALUE.search(value):
        violations.add("sensitive_value")


def _check(path: Path, violations: set[str]) -> bool:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        violations.add("invalid_json")
        return False
    if not isinstance(value, dict) or value.get("manifest_schema") not in ALLOWED_INPUT_SCHEMAS:
        violations.add("unexpected_manifest")
        return False

    schema = value["manifest_schema"]
    required = (
        {"metadata", "checks", "overall"}
        if schema == "patient-app-platform/release-evidence"
        else {"metadata", "decisions", "missing_evidence", "overall"}
    )
    if (
        value.get("schema_version") != "1.0.0"
        or any(key not in value for key in required)
        or not isinstance(value.get("metadata"), dict)
        or not isinstance(value.get("overall"), dict)
        or (schema.endswith("release-evidence") and not isinstance(value.get("checks"), dict))
        or (schema.endswith("production-gate") and (
            not isinstance(value.get("decisions"), dict)
            or not isinstance(value.get("missing_evidence"), list)
        ))
    ):
        violations.add("invalid_manifest")
        return False

    _walk(value, violations)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", required=True, help=argparse.SUPPRESS)
    parser.add_argument("--output", default="artifacts/privacy-evidence.json", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    violations: set[str] = set()
    checked = 0
    for raw in args.input:
        if _check(Path(raw), violations):
            checked += 1
    if checked != len(args.input):
        violations.add("input_unavailable")
    status = "passed" if not violations else "failed"
    manifest = {
        "manifest_schema": SCHEMA,
        "schema_version": VERSION,
        "status": status,
        "inputs_checked": checked,
        "violation_codes": sorted(violations),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    if violations:
        print("Privacy evidence check failed; inspect generated evidence locally.", file=sys.stderr)
        return 1
    print(f"Privacy evidence check passed ({checked} manifests).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
