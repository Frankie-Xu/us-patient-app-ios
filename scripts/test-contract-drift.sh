#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT
python_bin="${PYTHON_BIN:-python3}"

cp "$repo_root/packages/contracts/contract.routes.json" "$tmp_dir/original.routes.json"
cp "$tmp_dir/original.routes.json" "$tmp_dir/contract.routes.json"
VALIDATION_ROOT="$repo_root" "$python_bin" "$repo_root/scripts/check_contract_drift.py"

"$python_bin" - "$tmp_dir/contract.routes.json" <<'PY'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
value = json.loads(path.read_text())
value["routes"].pop()
path.write_text(json.dumps(value, indent=2) + "\n")
PY
set +e
cp "$tmp_dir/contract.routes.json" "$repo_root/packages/contracts/contract.routes.json"
VALIDATION_ROOT="$repo_root" "$python_bin" "$repo_root/scripts/check_contract_drift.py" >"$tmp_dir/output" 2>&1
status=$?
cp "$tmp_dir/original.routes.json" "$repo_root/packages/contracts/contract.routes.json"
set -e
test "$status" -eq 1
test "$(cat "$tmp_dir/output")" = "OpenAPI contract drift detected; update the reviewed route inventory."
echo "contract drift regression passed"
