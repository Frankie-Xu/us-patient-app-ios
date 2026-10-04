#!/usr/bin/env bash
set -euo pipefail

component_dir="${1:-services/api}"
artifact_path="${2:-${READINESS_ARTIFACT_PATH:-}}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec "${PYTHON_BIN:-python3}" "$script_dir/api_readiness_smoke.py" "${VALIDATION_ROOT:-$script_dir/..}" "$component_dir" "$artifact_path"
