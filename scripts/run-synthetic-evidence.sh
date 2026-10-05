#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT
python_bin="${PYTHON_BIN:-python3}"
"$python_bin" "$repo_root/scripts/production_gate.py" --mode synthetic --output "$tmp_dir/production-gate.json" >/dev/null
