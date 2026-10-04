#!/usr/bin/env bash
set -euo pipefail

repo_root="${VALIDATION_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$repo_root"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

redact_matches() {
  local matches_file="$1"
  test -s "$matches_file"
  echo "Matched values and paths are omitted from logs."
}

secret_matches="$tmp_dir/secrets.txt"
: > "$secret_matches"

# Keep the patterns focused on credential shapes and assignments. The output is
# redacted before it is printed so a failed CI job cannot become a secret sink.
secret_patterns=(
  '-----BEGIN ([A-Z0-9]+ )?PRIVATE KEY-----'
  '\b(AKIA|ASIA)[0-9A-Z]{16}\b'
  '\bgithub_pat_[A-Za-z0-9_]{20,}\b'
  '\bgh[pousr]_[A-Za-z0-9_]{20,}\b'
  '\bxox[baprs]-[A-Za-z0-9-]{10,}\b'
  '\bsk-[A-Za-z0-9]{20,}\b'
  '\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b'
  "(?i)\b(api[_-]?key|client[_-]?secret|password|secret|token|private[_-]?key)\s*[:=]\s*[\"']?[A-Za-z0-9_+=-]{16,}"
)

set +e
scan_args=()
for pattern in "${secret_patterns[@]}"; do
  scan_args+=(--pattern "$pattern")
done
python3 "$script_dir/scan-repo.py" --root "$repo_root" "${scan_args[@]}" >> "$secret_matches" 2>/dev/null
scan_status=$?
set -e
if [[ $scan_status -ne 0 ]]; then
  echo "Credential scan failed; refusing to continue." >&2
  exit 1
fi

if [[ -s "$secret_matches" ]]; then
  echo "Potential credential detected in repository files (details redacted):" >&2
  redact_matches "$secret_matches" >&2
  echo "Remove the credential before committing; use local environment configuration instead." >&2
  exit 1
fi

clinical_paths="$tmp_dir/clinical-paths.txt"
: > "$clinical_paths"

# These formats are document or imaging payloads rather than source fixtures.
find . -type f -not -path './.git/*' \( \
  -iname '*.pdf' -o -iname '*.dcm' -o -iname '*.dicom' -o -iname '*.hl7' -o \
  -iname '*.ccd' -o -iname '*.ccda' -o -iname '*.fhir' -o -iname '*.nii' -o \
  -iname '*.nii.gz' -o -iname '*.nrrd' -o -iname '*.mha' -o -iname '*.mhd' -o \
  -iname '*.svs' -o -iname '*.ndpi' -o -iname '*.heic' \
\) -print >> "$clinical_paths"

# Images and tabular/text exports are only suspicious when stored in a path
# that indicates patient or clinical payloads. This keeps ordinary product
# assets and documentation usable while catching likely accidental uploads.
while IFS= read -r path; do
  # Synthetic fixtures and samples are allowed; only explicit clinical payload
  # paths are treated as suspicious for image and export formats.
if [[ "$path" =~ (^|/)(testdata|uploads?|exports?|records?|documents?|clinical|medical|radiology|imaging)(/|$) ]] && \
     [[ "$path" =~ \.(csv|json|xml|txt|jpg|jpeg|png|tif|tiff|webp)$ ]]; then
    printf '%s\n' "$path" >> "$clinical_paths"
  fi
done < <(find . -type f -not -path './.git/*' -print)

if [[ -s "$clinical_paths" ]]; then
  echo "Potential clinical document found in repository (details redacted):" >&2
  echo "Matched paths are omitted from logs." >&2
  echo "Use synthetic or appropriately de-identified fixtures outside the repository." >&2
  exit 1
fi

# Catch common PHI labels in source, fixture, and export files while ignoring
# prose documentation. Values are redacted in the failure output.
phi_matches="$tmp_dir/phi.txt"
: > "$phi_matches"
set +e
python3 "$script_dir/scan-repo.py" --root "$repo_root" \
  --exclude '*.md' --exclude '*.html' \
  --pattern '(?i)\b(medical record number|mrn|date of birth|dob|social security number|ssn|patient name|diagnosis|discharge summary|medication list)\s*[:=]' \
  >> "$phi_matches" 2>/dev/null
phi_scan_status=$?
set -e
if [[ $phi_scan_status -ne 0 ]]; then
  echo "PHI-label scan failed; refusing to continue." >&2
  exit 1
fi

if [[ -s "$phi_matches" ]]; then
  echo "Potential PHI-labelled data found in repository files (details redacted):" >&2
  redact_matches "$phi_matches" >&2
  echo "Remove the data or replace it with approved synthetic fixtures." >&2
  exit 1
fi

echo "Repository validation passed."
