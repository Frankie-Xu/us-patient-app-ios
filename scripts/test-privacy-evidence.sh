#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT
python_bin="${PYTHON_BIN:-python3}"

cat > "$tmp_dir/release.json" <<'JSON'
{"manifest_schema":"patient-app-platform/release-evidence","schema_version":"1.0.0","metadata":{"commit_sha":"0123456789abcdef0123456789abcdef01234567","workflow_name":"CI","run_id":"42"},"checks":{},"overall":{"status":"passed"}}
JSON
cat > "$tmp_dir/gate.json" <<'JSON'
{"manifest_schema":"patient-app-platform/production-gate","schema_version":"1.0.0","metadata":{"baseline":"ADR-0003","mode":"synthetic","commit_sha":"0123456789abcdef0123456789abcdef01234567"},"decisions":{},"missing_evidence":[],"overall":{"status":"pause","production_phi_allowed":false}}
JSON
"$python_bin" "$repo_root/scripts/check_privacy_evidence.py" --input "$tmp_dir/release.json" --input "$tmp_dir/gate.json" --output "$tmp_dir/pass.json"
"$python_bin" - "$tmp_dir/pass.json" <<'PY'
import json, pathlib, sys
value=json.loads(pathlib.Path(sys.argv[1]).read_text())
assert value == {"inputs_checked": 2, "manifest_schema": "patient-app-platform/privacy-evidence", "schema_version": "1.0.0", "status": "passed", "violation_codes": []}
PY
cat > "$tmp_dir/leak.json" <<'JSON'
{"manifest_schema":"patient-app-platform/release-evidence","schema_version":"1.0.0","metadata":{"debug_path":"/Users/example/private.json","details":"patient name"},"checks":{},"overall":{"status":"passed"}}
JSON
set +e
"$python_bin" "$repo_root/scripts/check_privacy_evidence.py" --input "$tmp_dir/leak.json" --output "$tmp_dir/fail.json" >"$tmp_dir/output" 2>&1
status=$?
set -e
test "$status" -eq 1
grep -Fx "Privacy evidence check failed; inspect generated evidence locally." "$tmp_dir/output"
! grep -q "Users\|patient name\|private.json" "$tmp_dir/output"
"$python_bin" - "$tmp_dir/fail.json" <<'PY'
import json, pathlib, sys
value=json.loads(pathlib.Path(sys.argv[1]).read_text())
assert value["status"] == "failed"
assert value["violation_codes"] == ["sensitive_key", "sensitive_value"]
serialized=json.dumps(value)
assert "Users" not in serialized and "patient name" not in serialized
PY
cat > "$tmp_dir/query-leak.json" <<'JSON'
{"manifest_schema":"patient-app-platform/release-evidence","schema_version":"1.0.0","metadata":{"commit_sha":"0123456789abcdef0123456789abcdef01234567","callback":"https://example.test/cb?access_token=leaked-secret"},"checks":{},"overall":{"status":"passed"}}
JSON
set +e
"$python_bin" "$repo_root/scripts/check_privacy_evidence.py" --input "$tmp_dir/query-leak.json" --output "$tmp_dir/query-fail.json" >"$tmp_dir/query-output" 2>&1
status=$?
set -e
test "$status" -eq 1
"$python_bin" - "$tmp_dir/query-fail.json" <<'PY'
import json, pathlib, sys
value=json.loads(pathlib.Path(sys.argv[1]).read_text())
assert value["violation_codes"] == ["sensitive_value"]
PY

cat > "$tmp_dir/malformed.json" <<'JSON'
{"manifest_schema":"patient-app-platform/release-evidence","schema_version":"1.0.0","metadata":{},"overall":{"status":"passed"}}
JSON
set +e
"$python_bin" "$repo_root/scripts/check_privacy_evidence.py" --input "$tmp_dir/malformed.json" --output "$tmp_dir/malformed-fail.json" >"$tmp_dir/malformed-output" 2>&1
status=$?
set -e
test "$status" -eq 1
"$python_bin" - "$tmp_dir/malformed-fail.json" <<'PY'
import json, pathlib, sys
value=json.loads(pathlib.Path(sys.argv[1]).read_text())
assert value["violation_codes"] == ["input_unavailable", "invalid_manifest"]
PY

echo "privacy evidence regression passed"
