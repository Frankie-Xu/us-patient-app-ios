#!/usr/bin/env bash
set -euo pipefail

component_dir="${1:-services/ai}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -d "$component_dir" ]] || [[ ! -f "$component_dir/golden_set.py" ]]; then
  echo "Skipping AI golden-set regression: $component_dir evaluation component is not present yet."
  exit 0
fi

exec "${PYTHON_BIN:-python3}" "$script_dir/ai_golden_report.py" "${VALIDATION_ROOT:-$script_dir/..}" "$component_dir"
