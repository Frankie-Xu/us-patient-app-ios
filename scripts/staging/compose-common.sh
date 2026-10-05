#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root_dir="$(cd "$script_dir/../.." && pwd)"
compose_file="$root_dir/infra/staging/compose.yaml"
env_file="${STAGING_ENV_FILE:-$root_dir/.env.staging}"

if [[ ! -f "$env_file" ]]; then
  echo "staging env file is missing: $env_file" >&2
  echo "copy .env.staging.example to that path and replace every placeholder" >&2
  exit 2
fi

export ROOT_DIR="$root_dir"
export COMPOSE_FILE_PATH="$compose_file"
export STAGING_ENV_PATH="$env_file"

compose() {
  docker compose --env-file "$STAGING_ENV_PATH" --file "$COMPOSE_FILE_PATH" "$@"
}
