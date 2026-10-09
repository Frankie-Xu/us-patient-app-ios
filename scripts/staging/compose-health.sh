#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=compose-common.sh
source "$script_dir/compose-common.sh"

compose ps
api_port="$(awk -F= '/^STAGING_API_PORT=/{print $2}' "$STAGING_ENV_PATH" | tail -n 1)"
worker_port="$(awk -F= '/^STAGING_WORKER_PORT=/{print $2}' "$STAGING_ENV_PATH" | tail -n 1)"
api_port="${api_port:-58000}"
worker_port="${worker_port:-58001}"

wait_for_health() {
  local url="$1"
  local attempts=30
  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if curl --fail --silent --show-error "$url" >/dev/null; then
      return 0
    fi
    sleep 2
  done
  echo "health check timed out: $url" >&2
  return 1
}

wait_for_health "http://127.0.0.1:${api_port}/healthz"
wait_for_health "http://127.0.0.1:${api_port}/readyz"
wait_for_health "http://127.0.0.1:${worker_port}/healthz"
wait_for_health "http://127.0.0.1:${worker_port}/readyz"
echo "staging API and worker liveness/readiness checks passed"
