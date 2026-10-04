#!/usr/bin/env bash
set -euo pipefail

component_dir="${1:-services/ai}"
artifact_path="${2:-${AI_GOLDEN_ARTIFACT_PATH:-}}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec "${PYTHON_BIN:-python3}" "$script_dir/ai_golden_report.py" "${VALIDATION_ROOT:-$script_dir/..}" "$component_dir" "$artifact_path"
