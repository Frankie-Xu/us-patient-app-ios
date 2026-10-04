#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

export GITHUB_SHA="0123456789abcdef0123456789abcdef01234567"
export GITHUB_WORKFLOW="CI"
export RELEASE_EVIDENCE_WORKFLOW_VERSION="ci@1"
export GITHUB_RUN_ID="12345"
export GITHUB_RUN_NUMBER="9"

RELEASE_EVIDENCE_REPOSITORY_RESULT=success \
RELEASE_EVIDENCE_CONTRACT_RESULT=success \
RELEASE_EVIDENCE_API_RESULT=success \
RELEASE_EVIDENCE_AI_RESULT=success \
RELEASE_EVIDENCE_IOS_RESULT=skipped \
python3 "$repo_root/scripts/release_evidence.py" --from-ci --output "$tmp_dir/pass.json"

python3 - "$tmp_dir/pass.json" <<'PY'
import json, pathlib, sys
value=json.loads(pathlib.Path(sys.argv[1]).read_text())
assert value["manifest_schema"] == "patient-app-platform/release-evidence"
assert value["overall"]["status"] == "passed"
assert value["checks"]["ios"]["status"] == "skipped"
serialized=json.dumps(value)
for forbidden in ("services/", "scripts/", "PHI", "token", "patient name", "diagnosis"): assert forbidden not in serialized
PY

set +e
RELEASE_EVIDENCE_REPOSITORY_RESULT=failure \
RELEASE_EVIDENCE_CONTRACT_RESULT=success \
RELEASE_EVIDENCE_API_RESULT=success \
RELEASE_EVIDENCE_AI_RESULT=success \
RELEASE_EVIDENCE_IOS_RESULT=skipped \
python3 "$repo_root/scripts/release_evidence.py" --from-ci --output "$tmp_dir/fail.json"
status=$?
set -e
test "$status" -eq 1
python3 - "$tmp_dir/fail.json" <<'PY'
import json, pathlib, sys
value=json.loads(pathlib.Path(sys.argv[1]).read_text())
assert value["overall"]["status"] == "failed"
assert value["overall"]["failed_groups"] == ["repository"]
PY

echo "release evidence regression passed"
