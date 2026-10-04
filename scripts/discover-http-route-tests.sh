#!/usr/bin/env bash
set -euo pipefail

component_dir="${1:-services/api}"
if [[ ! -d "$component_dir" ]]; then
  echo "Skipping HTTP route discovery: $component_dir is not present yet."
  exit 0
fi

route_adapter="$(rg -l --glob '*.py' 'FastAPI\(|APIRouter\(' "$component_dir" || true)"
route_tests="$(find "$component_dir" \( -name .venv -o -name venv -o -name __pycache__ -o -name .pytest_cache \) -prune -o -type f \( -name 'test_*.py' -o -name '*_test.py' \) -print0 | while IFS= read -r -d '' test_file; do
  test_name="$(basename "$test_file")"
  if [[ "$test_name" == *route* || "$test_name" == *http* || "$test_name" == *endpoint* || "$test_name" == *app* ]] || \
     rg -q 'TestClient|ASGITransport|import httpx|from httpx|client\.(get|post|put|patch|delete)\(|healthz' "$test_file"; then
    printf '%s\n' "$test_file"
  fi
done)"

route_family_counts=()
for family in topics visits tasks; do
  family_count="$(find "$component_dir" \( -name .venv -o -name venv -o -name __pycache__ -o -name .pytest_cache \) -prune -o -type f \( -name 'test_*.py' -o -name '*_test.py' \) -print0 | while IFS= read -r -d '' test_file; do
    if rg -q "/v1/${family}([/?\"']|$)|client\.(get|post|put|patch|delete)\([^)]*${family}" "$test_file"; then
      printf '1\n'
    fi
  done | wc -l | tr -d ' ')"
  route_family_counts+=("$family=$family_count")
done
route_family_summary="$(IFS=', '; echo "${route_family_counts[*]}")"

if [[ -n "$route_tests" ]]; then
  count="$(printf '%s\n' "$route_tests" | sed '/^$/d' | wc -l | tr -d ' ')"
  echo "Discovered $count HTTP route test file(s); topics/visits/tasks coverage: $route_family_summary."
elif [[ -n "$route_adapter" ]]; then
  echo "No HTTP route test files discovered yet; topics/visits/tasks coverage: $route_family_summary. API tests still run for $component_dir."
else
  echo "Skipping HTTP route discovery: no FastAPI route adapter is present yet (topics/visits/tasks coverage: $route_family_summary)."
fi
