#!/usr/bin/env bash
set -euo pipefail

# Offline regression checks for ios-release-preflight.sh. A tiny xcodebuild
# shim supplies deterministic project/list/build-settings output, so these
# checks do not require Xcode, CoreSimulator, or a signing environment.

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
preflight="$repo_root/scripts/ios-release-preflight.sh"
tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/patient-app-release-preflight-test.XXXXXX")"
trap 'rm -rf "$tmp_dir"' EXIT

fake_project="$tmp_dir/PatientApp.xcodeproj"
fake_bin="$tmp_dir/bin"
mkdir -p "$fake_project" "$fake_bin"
printf '%s\n' '// deterministic preflight fixture' > "$fake_project/project.pbxproj"

cat > "$fake_bin/xcodebuild" <<'SHIM'
#!/usr/bin/env bash
set -euo pipefail

case " $* " in
  *" -version "*)
    printf '%s\n' 'Xcode 27.0' 'Build version 27A266a'
    ;;
  *" -list "*)
    cat <<'LIST'
Information about project "PatientApp":
    Targets:
        PatientApp
    Build Configurations:
        Debug
        Release
    Schemes:
        PatientApp-Debug
        PatientAppTests
LIST
    ;;
  *" -showBuildSettings "*)
    cat <<'SETTINGS'
Build settings for action build and target PatientApp:
    CONFIGURATION = Release
    CURRENT_PROJECT_VERSION = 1
    DEBUG_INFORMATION_FORMAT = dwarf-with-dsym
    INFOPLIST_FILE = Resources/Info.plist
    IPHONEOS_DEPLOYMENT_TARGET = 17.0
    MARKETING_VERSION = 0.1.0
    PRODUCT_BUNDLE_IDENTIFIER = com.example.patientapp
    SWIFT_VERSION = 6.0
    TARGET_NAME = PatientApp
SETTINGS
    ;;
  *)
    echo "unsupported fake xcodebuild invocation: $*" >&2
    exit 2
    ;;
esac
SHIM
chmod +x "$fake_bin/xcodebuild"

run_capture() {
  set +e
  output="$("$@" 2>&1)"
  status=$?
  set -e
}

base_env=(
  env
  "PATH=$fake_bin:$PATH"
  "IOS_PROJECT=$fake_project"
)

run_capture "${base_env[@]}" "$preflight"
if [[ "$status" -ne 0 ]]; then
  printf '%s\n' "$output" >&2
  echo "default preflight should pass (status $status)" >&2
  exit 1
fi
if ! grep -Fq "Preflight passed" <<<"$output"; then
  echo "default preflight did not report success" >&2
  exit 1
fi
echo "default configuration: passed"

run_capture "${base_env[@]}" \
  IOS_EXPECTED_BUNDLE_ID=com.example.patientapp.production \
  IOS_EXPECTED_MARKETING_VERSION=1.0.0 \
  "$preflight"
if [[ "$status" -ne 1 ]] || \
   ! grep -Fq "does not match IOS_EXPECTED_BUNDLE_ID" <<<"$output" || \
   ! grep -Fq "does not match IOS_EXPECTED_MARKETING_VERSION" <<<"$output"; then
  printf '%s\n' "$output" >&2
  echo "bundle/version mismatch should fail with both assertions (status $status)" >&2
  exit 1
fi
echo "bundle/version mismatch: blocked as expected"

run_capture "${base_env[@]}" IOS_PREFLIGHT_REQUIRE_SIGNING=1 "$preflight"
if [[ "$status" -ne 1 ]] || \
   ! grep -Fq "Release signing is required" <<<"$output"; then
  printf '%s\n' "$output" >&2
  echo "strict signing should fail with a clear message (status $status)" >&2
  exit 1
fi
echo "strict signing: blocked as expected"

echo "iOS release preflight offline regression checks passed."
