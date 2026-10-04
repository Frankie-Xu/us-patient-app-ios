#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

cp "$repo_root/packages/contracts/openapi.routes.json" "$tmp_dir/openapi.routes.json"
VALIDATION_ROOT="$repo_root" python3 "$repo_root/scripts/check_contract_drift.py"

python3 - "$tmp_dir/openapi.routes.json" <<'PY'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
value = json.loads(path.read_text())
value["routes"].pop()
path.write_text(json.dumps(value, indent=2) + "\n")
PY
set +e
cp "$tmp_dir/openapi.routes.json" "$repo_root/packages/contracts/openapi.routes.json.bak"
cp "$tmp_dir/openapi.routes.json" "$repo_root/packages/contracts/openapi.routes.json"
VALIDATION_ROOT="$repo_root" python3 "$repo_root/scripts/check_contract_drift.py" >"$tmp_dir/output" 2>&1
status=$?
rm -f "$repo_root/packages/contracts/openapi.routes.json"
mv "$repo_root/packages/contracts/openapi.routes.json.bak" "$repo_root/packages/contracts/openapi.routes.json"
set -e
test "$status" -eq 1
test "$(cat "$tmp_dir/output")" = "OpenAPI contract drift detected; update the reviewed route inventory."
echo "contract drift regression passed"
