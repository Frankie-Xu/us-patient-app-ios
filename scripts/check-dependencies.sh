#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

echo "Tool versions available to validation:"
git --version
command -v python3 >/dev/null && python3 --version || true
command -v node >/dev/null && node --version || true
command -v swift >/dev/null && swift --version | head -n 1 || true

while IFS= read -r -d '' manifest; do
  package_dir="$(dirname "$manifest")"
  if [[ ! -f "$package_dir/Package.swift" ]]; then
    continue
  fi
  if ! command -v swift >/dev/null; then
    echo "Package.swift is present but Swift is unavailable; dependency manifest check cannot run." >&2
    exit 1
  fi
  echo "Checking Swift package manifest: $package_dir/Package.swift"
  (cd "$package_dir" && swift package dump-package >/dev/null)
done < <(find . -type f -name Package.swift -not -path './.git/*' -not -path '*/.build/*' -not -path '*/Packages/*' -not -path '*/.swiftpm/*' -print0)

while IFS= read -r -d '' manifest; do
  echo "Checking Node manifest: $manifest"
  # shellcheck disable=SC2016
  node -e 'const fs = require("fs"); const p = process.argv[1]; const pkg = JSON.parse(fs.readFileSync(p, "utf8")); if (!pkg.name || !pkg.version) { throw new Error(`${p} must declare name and version`); }' "$manifest"
done < <(find . -type f -name package.json -not -path './.git/*' -not -path '*/.build/*' -not -path '*/Packages/*' -not -path '*/.swiftpm/*' -print0)

while IFS= read -r -d '' manifest; do
  echo "Checking Python project metadata: $manifest"
  python3 - "$manifest" <<'PY'
import pathlib
import sys

try:
    import tomllib
except ModuleNotFoundError as exc:
    raise SystemExit(f"Python 3.11+ is required to parse {sys.argv[1]}") from exc

with pathlib.Path(sys.argv[1]).open("rb") as stream:
    data = tomllib.load(stream)
project = data.get("project", {})
if project and not project.get("name"):
    raise SystemExit(f"{sys.argv[1]} has [project] metadata without a name")
PY
done < <(find . -type f -name pyproject.toml -not -path './.git/*' -not -path '*/.build/*' -not -path '*/Packages/*' -not -path '*/.swiftpm/*' -print0)

if [[ -f services/api/pyproject.toml && ! -f services/api/requirements-ci.txt ]]; then
  echo "services/api/requirements-ci.txt is required for reproducible API test installs." >&2
  exit 1
fi

echo "Dependency manifest checks passed."
