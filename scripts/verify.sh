#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

python_bin="${PYTHON_BIN:-python3}"
if ! "$python_bin" -c 'import yaml, jsonschema, openapi_spec_validator, pytest' >/dev/null 2>&1; then
  if ! command -v uv >/dev/null 2>&1; then
    echo "Pinned CI Python tools are missing. Install scripts/requirements-ci.txt or install uv." >&2
    exit 1
  fi
  venv_root="${VERIFY_VENV_PATH:-${TMPDIR:-/tmp}/patient-app-ci-venv}"
  if [[ ! -x "$venv_root/bin/python" ]]; then
    uv venv --seed "$venv_root" >/dev/null
  elif ! "$venv_root/bin/python" -m pip --version >/dev/null 2>&1; then
    uv venv --seed --allow-existing "$venv_root" >/dev/null
  fi
  uv pip install --python "$venv_root/bin/python" --quiet -r scripts/requirements-ci.txt
  python_bin="$venv_root/bin/python"
fi
export PYTHON_BIN="$python_bin"

usage() {
  cat <<'EOF'
Usage: bash scripts/verify.sh [--quick|--full]

  --quick  Run fast repository, dependency, workflow-pin, and patch checks.
  --full   Run the same release evidence gate used by CI (default).
EOF
}

mode="full"
case "${1:-}" in
  "") ;;
  --quick) mode="quick" ;;
  --full) mode="full" ;;
  -h|--help) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac

if [[ "$mode" == "quick" ]]; then
  bash scripts/validate-repo.sh
  bash scripts/check-dependencies.sh
  bash scripts/check-workflow-pins.sh
  git diff --check
  echo "Quick verification passed. Run 'bash scripts/verify.sh --full' before opening a pull request."
  exit 0
fi

artifact_path="${VERIFY_ARTIFACT_PATH:-artifacts/release-evidence.json}"
set +e
"$python_bin" scripts/release_evidence.py --output "$artifact_path"
status=$?
set -e

"$python_bin" - "$artifact_path" <<'PY'
import json
import pathlib
import sys

value = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
overall = value["overall"]
print(
    f"Verification {overall['status']}: "
    f"{overall['passed_groups']} passed, "
    f"{overall['skipped_groups']} skipped, "
    f"{len(overall['failed_groups'])} failed."
)
if overall["failed_groups"]:
    print("Failed groups: " + ", ".join(overall["failed_groups"]))
print("Evidence: " + str(pathlib.Path(sys.argv[1])))
PY
exit "$status"
