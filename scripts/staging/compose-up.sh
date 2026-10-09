#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=compose-common.sh
source "$script_dir/compose-common.sh"

compose up --build --detach
"$script_dir/compose-health.sh"
