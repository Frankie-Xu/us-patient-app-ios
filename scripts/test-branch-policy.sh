#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${PYTHON_BIN:-python3}"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

cat > "$tmp_dir/stacked.json" <<'JSON'
{"pull_request":{"labels":[{"name":"stacked"}],"body":"Parent PR: #73"}}
JSON

GITHUB_HEAD_REF="feat/example-child" \
GITHUB_BASE_REF="feat/example-parent" \
GITHUB_EVENT_PATH="$tmp_dir/stacked.json" \
  "$python_bin" "$repo_root/scripts/check_branch_policy.py"

cat > "$tmp_dir/missing.json" <<'JSON'
{"pull_request":{"labels":[],"body":"No parent reference"}}
JSON

set +e
GITHUB_HEAD_REF="feat/example-child" \
GITHUB_BASE_REF="feat/example-parent" \
GITHUB_EVENT_PATH="$tmp_dir/missing.json" \
  "$python_bin" "$repo_root/scripts/check_branch_policy.py" > "$tmp_dir/output" 2>&1
status=$?
set -e
test "$status" -eq 1
grep -F "stacked pull requests must carry the 'stacked' label" "$tmp_dir/output"
grep -F "stacked pull requests must reference a parent or base PR" "$tmp_dir/output"

echo "Branch policy regression tests passed."
