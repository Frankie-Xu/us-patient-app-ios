#!/usr/bin/env python3
"""Evaluate ADR-0003 evidence without serializing evidence content.

Production mode requires a strict boolean evidence register. Synthetic mode
always emits an explicit pause manifest so implementation can proceed without
implying approval for production PHI.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

MANIFEST_SCHEMA = "patient-app-platform/production-gate"
MANIFEST_VERSION = "1.0.0"
INPUT_SCHEMA = "patient-app-platform/production-gate-input"
INPUT_VERSION = "1.0.0"
_SAFE_SHA = re.compile(r"^[0-9a-f]{7,64}$")

# This register mirrors ADR-0003 D1-D8. Values must be booleans; the manifest
# emits only these fixed identifiers and statuses, never input text or paths.
REQUIREMENTS: OrderedDict[str, tuple[str, ...]] = OrderedDict(
    [
        ("D1", ("pilot_scope", "role_scope", "product_owner_signoff")),
        ("D2", ("service_entity", "us_region", "baa_dpa", "compliance_owner_signoff")),
        ("D3", ("oidc_gateway", "mfa_recovery", "reviewer_scope", "provider_approval", "compliance_owner_signoff")),
        ("D4", ("online_default", "cache_purge", "logout_switch_purge", "offline_no_go_ack")),
        ("D5", ("retention_30d", "deletion_cross_store", "legal_hold", "deletion_verification", "compliance_owner_signoff")),
        ("D6", ("share_24h", "resource_version_recipient_scope", "revoke_recheck", "download_copy_disclosure")),
        ("D7", ("telemetry_redaction", "operational_7d", "audit_90d", "key_rotation_90d", "key_revoke")),
        ("D8", ("product_owner_signoff", "compliance_security_owner_signoff", "engineering_owner_signoff", "incident_owner_signoff", "incident_exercise", "evidence_register")),
    ]
)


class GateInputError(ValueError):
    pass


def _commit(root: Path) -> str:
    supplied = os.environ.get("GITHUB_SHA", "")
    if _SAFE_SHA.fullmatch(supplied):
        return supplied
    try:
        value = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=10, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return value if _SAFE_SHA.fullmatch(value) else "unknown"


def _metadata(root: Path, mode: str) -> dict[str, str]:
    return {
        "baseline": "ADR-0003",
        "mode": mode,
        "commit_sha": _commit(root),
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }


def _strict_register(value: Any) -> dict[str, dict[str, bool]]:
    if not isinstance(value, Mapping):
        raise GateInputError("register must be an object")
    if set(value) != {"input_schema", "schema_version", "decisions"}:
        raise GateInputError("register envelope does not match the input schema")
    if value["input_schema"] != INPUT_SCHEMA or value["schema_version"] != INPUT_VERSION:
        raise GateInputError("register schema version is invalid")
    value = value["decisions"]
    if set(value) != set(REQUIREMENTS):
        raise GateInputError("register decision set does not match ADR-0003")
    result: dict[str, dict[str, bool]] = {}
    for decision, required in REQUIREMENTS.items():
        entry = value[decision]
        if not isinstance(entry, Mapping) or set(entry) != {"evidence"} or not isinstance(entry["evidence"], Mapping):
            raise GateInputError("decision evidence shape is invalid")
        evidence = entry["evidence"]
        if set(evidence) != set(required) or any(type(evidence[key]) is not bool for key in required):
            raise GateInputError("decision evidence keys or values are invalid")
        result[decision] = {key: evidence[key] for key in required}
    return result


def _production(register: dict[str, dict[str, bool]] | None, root: Path, invalid: bool = False) -> dict[str, Any]:
    missing: list[dict[str, str]] = []
    statuses: dict[str, str] = {}
    if invalid or register is None:
        for decision in REQUIREMENTS:
            statuses[decision] = "no-go"
        return _manifest(root, "production", statuses, [{"decision": "INPUT", "evidence": "valid_register"}], ["invalid_evidence_register"])
    for decision, required in REQUIREMENTS.items():
        absent = [key for key in required if not register[decision][key]]
        statuses[decision] = "go" if not absent else "no-go"
        missing.extend({"decision": decision, "evidence": key} for key in absent)
    return _manifest(root, "production", statuses, missing, ["required_evidence_missing"] if missing else [])


def _synthetic(root: Path) -> dict[str, Any]:
    statuses = {decision: "pause" for decision in REQUIREMENTS}
    missing = [{"decision": decision, "evidence": key} for decision, required in REQUIREMENTS.items() for key in required]
    return _manifest(root, "synthetic", statuses, missing, ["synthetic_mode"])


def _manifest(root: Path, mode: str, statuses: dict[str, str], missing: list[dict[str, str]], reasons: list[str]) -> dict[str, Any]:
    no_go = mode == "production" and bool(missing)
    overall = "no-go" if no_go else ("pause" if mode == "synthetic" else "go")
    return {
        "manifest_schema": MANIFEST_SCHEMA,
        "schema_version": MANIFEST_VERSION,
        "metadata": _metadata(root, mode),
        "decisions": {decision: {"status": statuses[decision]} for decision in REQUIREMENTS},
        "missing_evidence": missing,
        "overall": {
            "status": overall,
            "production_phi_allowed": overall == "go",
            "reasons": reasons,
            "no_go": no_go,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("production", "synthetic"), default="production")
    parser.add_argument("--evidence", help="strict boolean evidence register JSON")
    parser.add_argument("--output", default="artifacts/production-gate.json")
    args = parser.parse_args(argv)
    root = Path(os.environ.get("VALIDATION_ROOT", Path(__file__).resolve().parents[1])).resolve()
    invalid = False
    register = None
    if args.mode == "production":
        if not args.evidence:
            invalid = True
        else:
            try:
                register = _strict_register(json.loads(Path(args.evidence).read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError, GateInputError):
                invalid = True
    manifest = _synthetic(root) if args.mode == "synthetic" else _production(register, root, invalid)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    return 0 if manifest["overall"]["status"] in {"go", "pause"} else 1


if __name__ == "__main__":
    sys.exit(main())
