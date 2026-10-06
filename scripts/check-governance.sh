#!/usr/bin/env bash
set -euo pipefail

repo_root="${VALIDATION_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
exec "${PYTHON_BIN:-python3}" "$repo_root/scripts/check_repository_governance.py" "$repo_root"
