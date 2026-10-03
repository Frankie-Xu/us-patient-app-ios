#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if rg -n --hidden -g '!/.git/**' -g '!docs/technology-route.md' '(sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|-----BEGIN (RSA|OPENSSH|PRIVATE) KEY-----)' .; then
  echo "Potential credential detected; remove it before committing." >&2
  exit 1
fi

if find . -type f \( -iname '*.pdf' -o -iname '*.dcm' -o -iname '*.heic' \) -not -path './.git/*' | grep -q .; then
  echo "Potential clinical document found in repository; use synthetic fixtures outside the repo." >&2
  exit 1
fi

echo "Repository validation passed."

