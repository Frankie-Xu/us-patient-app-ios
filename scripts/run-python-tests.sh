#!/usr/bin/env bash
set -euo pipefail
component_dir="${1:?component directory is required}"
python_bin="${PYTHON_BIN:-python3}"
if [[ ! -d "$component_dir" ]]; then
  echo "Skipping Python tests: component is not present yet."
  exit 0
fi
test_files="$(find "$component_dir" \( -name .venv -o -name venv -o -name __pycache__ \) -prune -o -type f \( -name 'test_*.py' -o -name '*_test.py' \) -print)"
if [[ -z "$test_files" ]]; then
  echo "Skipping $component_dir tests: no Python test files are present yet."
  exit 0
fi
# Use the pinned pytest from scripts/requirements-ci.txt for both unittest and
# pytest suites. Missing pytest, import errors and zero collected tests fail.
for requirements in requirements.txt requirements-dev.txt; do
  if [[ -f "$component_dir/$requirements" ]]; then
    "$python_bin" -m pip install --disable-pip-version-check --no-input -r "$component_dir/$requirements"
  fi
done
if [[ -f "$component_dir/pyproject.toml" ]]; then
  "$python_bin" - "$component_dir/pyproject.toml" <<'PY'
import subprocess
import sys
import tomllib
from pathlib import Path
project = tomllib.loads(Path(sys.argv[1]).read_text()).get("project", {})
deps = project.get("dependencies", []) + project.get("optional-dependencies", {}).get("test", [])
if deps:
    subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-input", *deps], check=True)
PY
fi
"$python_bin" -m pip check
PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}" "$python_bin" -m pytest "$component_dir" --import-mode=importlib --tb=no --show-capture=no
