#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT
python_bin="${PYTHON_BIN:-python3}"

cat > "$tmp_dir/all.json" <<'JSON'
{
  "input_schema": "patient-app-platform/production-gate-input",
  "schema_version": "1.0.0",
  "decisions": {
    "D1": {"evidence": {"pilot_scope": true, "role_scope": true, "product_owner_signoff": true}},
    "D2": {"evidence": {"service_entity": true, "us_region": true, "baa_dpa": true, "compliance_owner_signoff": true}},
    "D3": {"evidence": {"oidc_gateway": true, "mfa_recovery": true, "reviewer_scope": true, "provider_approval": true, "compliance_owner_signoff": true}},
    "D4": {"evidence": {"online_default": true, "cache_purge": true, "logout_switch_purge": true, "offline_no_go_ack": true}},
    "D5": {"evidence": {"retention_30d": true, "deletion_cross_store": true, "legal_hold": true, "deletion_verification": true, "compliance_owner_signoff": true}},
    "D6": {"evidence": {"share_24h": true, "resource_version_recipient_scope": true, "revoke_recheck": true, "download_copy_disclosure": true}},
    "D7": {"evidence": {"telemetry_redaction": true, "operational_7d": true, "audit_90d": true, "key_rotation_90d": true, "key_revoke": true}},
    "D8": {"evidence": {"product_owner_signoff": true, "compliance_security_owner_signoff": true, "engineering_owner_signoff": true, "incident_owner_signoff": true, "incident_exercise": true, "evidence_register": true}}
  }
}
JSON
"$python_bin" "$repo_root/scripts/production_gate.py" --mode production --evidence "$tmp_dir/all.json" --output "$tmp_dir/go.json"
"$python_bin" - "$tmp_dir/go.json" <<'PY'
import json, pathlib, sys
value=json.loads(pathlib.Path(sys.argv[1]).read_text())
assert value["overall"] == {"failed": False} if False else value["overall"]["status"] == "go"
assert value["overall"]["production_phi_allowed"] is True
assert value["missing_evidence"] == []
serialized=json.dumps(value)
for forbidden in ("services/", "scripts/", "token", "PHI", "patient name", "diagnosis"): assert forbidden not in serialized
PY

"$python_bin" - "$tmp_dir/all.json" <<'PY'
import json, pathlib, sys
value=json.loads(pathlib.Path(sys.argv[1]).read_text())
value["decisions"]["D2"]["evidence"]["baa_dpa"] = False
value["decisions"]["D4"]["evidence"]["cache_purge"] = False
value["decisions"]["D5"]["evidence"]["deletion_cross_store"] = False
value["decisions"]["D6"]["evidence"]["revoke_recheck"] = False
value["decisions"]["D7"]["evidence"]["telemetry_redaction"] = False
value["decisions"]["D7"]["evidence"]["key_rotation_90d"] = False
value["decisions"]["D8"]["evidence"]["compliance_security_owner_signoff"] = False
pathlib.Path(sys.argv[1]).write_text(json.dumps(value))
PY
set +e
"$python_bin" "$repo_root/scripts/production_gate.py" --mode production --evidence "$tmp_dir/all.json" --output "$tmp_dir/no-go.json"
status=$?
set -e
test "$status" -eq 1
"$python_bin" - "$tmp_dir/no-go.json" <<'PY'
import json, pathlib, sys
value=json.loads(pathlib.Path(sys.argv[1]).read_text())
assert value["overall"]["status"] == "no-go"
missing={(item["decision"],item["evidence"]) for item in value["missing_evidence"]}
for item in (("D2","baa_dpa"),("D4","cache_purge"),("D5","deletion_cross_store"),("D6","revoke_recheck"),("D7","telemetry_redaction"),("D7","key_rotation_90d"),("D8","compliance_security_owner_signoff")): assert item in missing
assert value["overall"]["production_phi_allowed"] is False
PY

"$python_bin" "$repo_root/scripts/production_gate.py" --mode synthetic --output "$tmp_dir/pause.json"
"$python_bin" - "$tmp_dir/pause.json" <<'PY'
import json, pathlib, sys
value=json.loads(pathlib.Path(sys.argv[1]).read_text())
assert value["overall"]["status"] == "pause"
assert value["overall"]["production_phi_allowed"] is False
assert all(item["status"] == "pause" for item in value["decisions"].values())
PY

echo "production gate regression passed"
