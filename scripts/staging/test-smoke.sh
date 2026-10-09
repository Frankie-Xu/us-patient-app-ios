#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root_dir="$(cd "$script_dir/../.." && pwd)"
artifact_path="$(mktemp -t patient-app-staging-smoke.XXXXXX.json)"
trap 'rm -f "$artifact_path"' EXIT

"$script_dir/run-smoke.sh" "$artifact_path"
"${PYTHON_BIN:-python3}" - "$artifact_path" <<'PY'
import json
import sys
from pathlib import Path

report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert report["status"] == "passed"
assert report["data_classification"] == "synthetic"
assert report["stages"]["processing_retry"]["status"] == "passed"
assert report["stages"]["conflict_gate"]["delivery_blocked"] is True
assert report["stages"]["share_and_revoke"]["revoked_access"] == "blocked"
print("staging smoke regression passed")
PY
