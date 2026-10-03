#!/usr/bin/env bash
set -euo pipefail

component_dir="${1:?component directory is required}"

if [[ ! -d "$component_dir" ]] || ! find "$component_dir" -type f -not -name .gitkeep -print -quit | grep -q .; then
  echo "Skipping $component_dir tests: component is not present yet."
  exit 0
fi

test_files="$(find "$component_dir" -type f \( -name 'test_*.py' -o -name '*_test.py' \) -print -quit)"
if [[ -z "$test_files" ]]; then
  echo "Skipping $component_dir tests: no Python test files are present yet."
  exit 0
fi

python_bin="${PYTHON_BIN:-python3}"
if [[ -f "$component_dir/requirements.txt" ]]; then
  "$python_bin" -m pip install --disable-pip-version-check --no-input -r "$component_dir/requirements.txt"
elif [[ -f "$component_dir/requirements-dev.txt" ]]; then
  "$python_bin" -m pip install --disable-pip-version-check --no-input -r "$component_dir/requirements-dev.txt"
fi

if "$python_bin" -c 'import pytest' >/dev/null 2>&1; then
  echo "Running $component_dir pytest tests..."
  "$python_bin" -m pytest "$component_dir"
else
  echo "Running $component_dir unittest tests..."
  "$python_bin" -m unittest discover -s "$component_dir" -p 'test*.py'
fi
