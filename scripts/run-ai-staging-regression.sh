#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_path="${1:-${AI_STAGING_ARTIFACT_PATH:-$repo_root/artifacts/ai-staging-regression.json}}"

PYTHONPATH="$repo_root${PYTHONPATH:+:$PYTHONPATH}" \
  "${PYTHON_BIN:-python3}" - "$repo_root" "$output_path" <<'PY'
import json
import sys
from pathlib import Path

from services.ai.staging_adapter import StagingAdapter, load_staging_inputs

root = Path(sys.argv[1])
output = Path(sys.argv[2])
inputs = load_staging_inputs(root / "services/ai/fixtures/staging_adapter_input.json")
report = StagingAdapter(clock=lambda: 10.0).regression_report(inputs)
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"AI staging regression passed ({report.sample_count} cases; delivery_blocked={report.delivery_blocked}).")
PY
