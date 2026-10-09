#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=compose-common.sh
source "$script_dir/compose-common.sh"

if [[ "${STAGING_REMOVE_VOLUMES:-0}" == "1" ]]; then
  compose down --volumes
else
  compose down
fi
