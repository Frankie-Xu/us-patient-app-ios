#!/usr/bin/env bash
set -euo pipefail

component_dir="${1:-services/api}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -d "$component_dir" ]] || [[ ! -f "$component_dir/app.py" ]]; then
  echo "Skipping API readiness smoke: $component_dir app adapter is not present yet."
  exit 0
fi

exec "${PYTHON_BIN:-python3}" "$script_dir/api_readiness_smoke.py" "${VALIDATION_ROOT:-$script_dir/..}" "$component_dir"
