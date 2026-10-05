#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root_dir="$(cd "$script_dir/../.." && pwd)"
env_file="${STAGING_ENV_FILE:-$root_dir/.env.staging.example}"
compose_file="$root_dir/infra/staging/compose.yaml"

docker compose --env-file "$env_file" --file "$compose_file" config --quiet
bash -n \
  "$script_dir/compose-common.sh" \
  "$script_dir/compose-up.sh" \
  "$script_dir/compose-down.sh" \
  "$script_dir/compose-health.sh"
python3 -m py_compile "$script_dir/worker.py"
echo "staging compose configuration regression passed"
