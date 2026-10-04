#!/bin/sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
env_file=$(mktemp)
rendered_config=$(mktemp)
cleanup() {
  rm -f "$env_file" "$rendered_config"
}
trap cleanup EXIT

cp "$repo_root/infra/staging/.env.example" "$env_file"
docker compose --env-file "$env_file" -f "$repo_root/infra/staging/docker-compose.yml" config --quiet
docker compose --env-file "$env_file" -f "$repo_root/infra/staging/docker-compose.yml" config --format json >"$rendered_config"
python3 "$repo_root/scripts/staging/validate_runtime.py" "$rendered_config"

# The full synthetic workflow already lives in scripts/staging_e2e.py. Reuse it
# when the caller's checkout includes that companion change; this runtime
# contract must not fork or duplicate the end-to-end implementation.
if [ -f "$repo_root/scripts/staging_e2e.py" ]; then
  python3 "$repo_root/scripts/staging_e2e.py"
else
  echo "staging_e2e.py not present; runtime composition contract passed"
fi
