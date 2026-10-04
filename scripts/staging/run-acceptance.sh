#!/bin/sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
summary_path=${STAGING_ACCEPTANCE_OUTPUT:-}
set -- "$repo_root/scripts/staging/acceptance_smoke.py"
if [ "${STAGING_ACCEPTANCE_ALLOW_MISSING_FULL_FLOW:-0}" = "1" ]; then
  set -- "$@" --allow-missing-full-flow
fi
if [ -n "$summary_path" ]; then
  set -- "$@" --output "$summary_path"
fi
exec python3 "$@"
