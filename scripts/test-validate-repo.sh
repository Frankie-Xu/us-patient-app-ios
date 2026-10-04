#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

run_failure_case() {
  local name="$1"
  local relative_path="$2"
  local contents="$3"
  local expected_message="$4"
  local case_root
  local output

  case_root="$(mktemp -d)"
  mkdir -p "$case_root/$(dirname "$relative_path")"
  printf '%s\n' "$contents" > "$case_root/$relative_path"
  if output="$(VALIDATION_ROOT="$case_root" bash "$script_dir/validate-repo.sh" 2>&1)"; then
    rm -rf "$case_root"
    echo "$name unexpectedly passed" >&2
    exit 1
  fi
  rm -rf "$case_root"
  if [[ "$output" != *"$expected_message"* ]]; then
    echo "$name did not report the expected scanner category" >&2
    exit 1
  fi
  if [[ "$output" == *"$contents"* ]]; then
    echo "$name printed the synthetic matched value" >&2
    exit 1
  fi
  echo "$name: failed and redacted"
}

synthetic_secret="AKIA$(printf '%016d' 0)"
run_failure_case "synthetic secret shape" "scratch/credential.txt" "$synthetic_secret" "Potential credential detected"
synthetic_phi_label="$(printf '%s' MRN): SYNTHETIC-0001"
run_failure_case "synthetic PHI label" "scratch/record.txt" "$synthetic_phi_label" "Potential PHI-labelled data found"

clinical_root="$(mktemp -d)"
mkdir -p "$clinical_root/fixtures"
touch "$clinical_root/fixtures/synthetic-document.pdf"
if clinical_output="$(VALIDATION_ROOT="$clinical_root" bash "$script_dir/validate-repo.sh" 2>&1)"; then
  rm -rf "$clinical_root"
  echo "synthetic clinical document unexpectedly passed" >&2
  exit 1
fi
rm -rf "$clinical_root"
if [[ "$clinical_output" != *"Potential clinical document found"* ]]; then
  echo "synthetic clinical document did not report the expected scanner category" >&2
  exit 1
fi
echo "synthetic clinical document: failed and reported location only"

clean_root="$(mktemp -d)"
printf '%s\n' 'synthetic fixture policy' > "$clean_root/README.md"
VALIDATION_ROOT="$clean_root" bash "$script_dir/validate-repo.sh" >/dev/null
rm -rf "$clean_root"
echo "clean synthetic repository: passed"
