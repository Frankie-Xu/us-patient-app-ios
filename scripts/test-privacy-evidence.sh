#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

cat > "$tmp_dir/release.json" <<'JSON'
{"manifest_schema":"patient-app-platform/release-evidence","schema_version":"1.0.0","metadata":{"commit_sha":"0123456789abcdef0123456789abcdef01234567","workflow_name":"CI","run_id":"42"},"overall":{"status":"passed"}}
JSON
cat > "$tmp_dir/gate.json" <<'JSON'
{"manifest_schema":"patient-app-platform/production-gate","schema_version":"1.0.0","metadata":{"baseline":"ADR-0003","mode":"synthetic","commit_sha":"0123456789abcdef0123456789abcdef01234567"},"overall":{"status":"pause","production_phi_allowed":false}}
JSON
python3 "$repo_root/scripts/check_privacy_evidence.py" --input "$tmp_dir/release.json" --input "$tmp_dir/gate.json" --output "$tmp_dir/pass.json"
python3 - "$tmp_dir/pass.json" <<'PY'
import json, pathlib, sys
value=json.loads(pathlib.Path(sys.argv[1]).read_text())
assert value == {"inputs_checked": 2, "manifest_schema": "patient-app-platform/privacy-evidence", "schema_version": "1.0.0", "status": "passed", "violation_codes": []}
PY
cat > "$tmp_dir/leak.json" <<'JSON'
{"manifest_schema":"patient-app-platform/release-evidence","debug_path":"/Users/example/private.json","details":"patient name"}
JSON
set +e
python3 "$repo_root/scripts/check_privacy_evidence.py" --input "$tmp_dir/leak.json" --output "$tmp_dir/fail.json" >"$tmp_dir/output" 2>&1
status=$?
set -e
test "$status" -eq 1
grep -Fx "Privacy evidence check failed; inspect generated evidence locally." "$tmp_dir/output"
! grep -q "Users\|patient name\|private.json" "$tmp_dir/output"
python3 - "$tmp_dir/fail.json" <<'PY'
import json, pathlib, sys
value=json.loads(pathlib.Path(sys.argv[1]).read_text())
assert value["status"] == "failed"
assert value["violation_codes"] == ["sensitive_key", "sensitive_value"]
serialized=json.dumps(value)
assert "Users" not in serialized and "patient name" not in serialized
PY
echo "privacy evidence regression passed"
