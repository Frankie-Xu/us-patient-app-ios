#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root_dir="$(cd "$script_dir/../.." && pwd)"
artifact_path="${1:-$root_dir/artifacts/staging/staging-smoke-report.json}"

exec "${PYTHON_BIN:-python3}" "$script_dir/staging_smoke.py" --root "$root_dir" --artifact "$artifact_path"
