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

curl --fail --silent --show-error "http://127.0.0.1:${api_port}/healthz" >/dev/null
curl --fail --silent --show-error "http://127.0.0.1:${worker_port}/healthz" >/dev/null
echo "staging API and worker health checks passed"
