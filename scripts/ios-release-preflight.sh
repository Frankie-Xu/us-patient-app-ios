#!/usr/bin/env bash
set -euo pipefail

# Check the checked-in iOS host before an archive or TestFlight upload. The
# script is intentionally read-only: it never changes signing, versions, or
# Xcode project files. Host-specific signing can be required with
# IOS_PREFLIGHT_REQUIRE_SIGNING=1.

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
project_path="${IOS_PROJECT:-$repo_root/apps/ios/PatientApp.xcodeproj}"
release_scheme="${IOS_RELEASE_SCHEME:-PatientApp-Debug}"
test_scheme="${IOS_TEST_SCHEME:-PatientAppTests}"
release_configuration="${IOS_RELEASE_CONFIGURATION:-Release}"
expected_bundle_id="${IOS_EXPECTED_BUNDLE_ID:-}"
expected_marketing_version="${IOS_EXPECTED_MARKETING_VERSION:-}"
expected_build_number="${IOS_EXPECTED_BUILD_NUMBER:-}"
require_signing="${IOS_PREFLIGHT_REQUIRE_SIGNING:-0}"
crash_monitoring_config="${IOS_CRASH_MONITORING_CONFIG:-$repo_root/artifacts/xcode/crash-monitoring.example.json}"

failures=()
warnings=()

pass() { printf '[PASS] %s\n' "$1"; }
warn() {
  warnings+=("$1")
  printf '[WARN] %s\n' "$1"
}
fail() {
  failures+=("$1")
  printf '[FAIL] %s\n' "$1" >&2
}

is_true() {
  case "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" in
    1|true|yes|y) return 0 ;;
    *) return 1 ;;
  esac
}

trim_setting() {
  local value="$1"
  value="$(printf '%s' "$value" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
  value="${value#\"}"
  value="${value%\"}"
  printf '%s' "$value"
}

setting() {
  local key="$1"
  sed -n "s/^[[:space:]]*${key}[[:space:]]*=[[:space:]]*//p" "$build_settings_file" | head -n 1 | {
    IFS= read -r value || true
    trim_setting "${value:-}"
  }
}

plist_value() {
  local key="$1"
  /usr/libexec/PlistBuddy -c "Print :$key" "$info_plist" 2>/dev/null || true
}

echo "iOS Release/TestFlight preflight"
echo "Project: $project_path"
echo "Release scheme: $release_scheme ($release_configuration)"
echo "Test scheme: $test_scheme"

if [[ ! -d "$project_path" || ! -f "$project_path/project.pbxproj" ]]; then
  fail "Xcode project is missing: $project_path"
else
  pass "Xcode project exists"
fi

if ! command -v xcodebuild >/dev/null 2>&1; then
  fail "xcodebuild is not available on PATH"
  xcodebuild_available=0
else
  xcodebuild_available=1
  xcode_version="$(xcodebuild -version 2>/dev/null | tr '\n' ' ' | sed 's/[[:space:]]\+/ /g' || true)"
  pass "Xcode available (${xcode_version:-unknown version})"
fi

if ! command -v /usr/libexec/PlistBuddy >/dev/null 2>&1; then
  fail "PlistBuddy is not available for Info.plist validation"
fi

tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/patient-app-release-preflight.XXXXXX")"
trap 'rm -rf "$tmp_dir"' EXIT
list_file="$tmp_dir/xcode-list.txt"
list_error="$tmp_dir/xcode-list.err"
build_settings_file="$tmp_dir/release-build-settings.txt"
build_settings_error="$tmp_dir/release-build-settings.err"

if (( xcodebuild_available == 1 )) && [[ -d "$project_path" ]]; then
  if xcodebuild -project "$project_path" -list >"$list_file" 2>"$list_error"; then
    pass "xcodebuild -list succeeded"
    configurations="$(sed -n '/Build Configurations:/,/Schemes:/p' "$list_file" | sed '1d;$d' | sed 's/^[[:space:]]*//')"
    schemes="$(sed -n '/Schemes:/,$p' "$list_file" | sed '1d' | sed 's/^[[:space:]]*//')"
    if printf '%s\n' "$configurations" | grep -Fqx "$release_configuration"; then
      pass "Build configuration exists: $release_configuration"
    else
      fail "Build configuration is missing: $release_configuration"
    fi
    if printf '%s\n' "$schemes" | grep -Fqx "$release_scheme"; then
      pass "Release scheme exists: $release_scheme"
    else
      fail "Release scheme is missing: $release_scheme"
    fi
    if printf '%s\n' "$schemes" | grep -Fqx "$test_scheme"; then
      pass "Test scheme exists: $test_scheme"
    else
      fail "Test scheme is missing: $test_scheme"
    fi
  else
    fail "xcodebuild -list failed; inspect $list_error"
  fi
fi

if (( xcodebuild_available == 1 )) && [[ -d "$project_path" ]]; then
  if xcodebuild -project "$project_path" \
      -scheme "$release_scheme" \
      -configuration "$release_configuration" \
      -derivedDataPath "$tmp_dir/DerivedData" \
      -showBuildSettings >"$build_settings_file" 2>"$build_settings_error"; then
    pass "Release build settings resolved"
  else
    fail "Release build settings could not be resolved; inspect $build_settings_error"
  fi
fi

if [[ -s "$build_settings_file" ]]; then
  target_name="$(setting TARGET_NAME)"
  bundle_id="$(setting PRODUCT_BUNDLE_IDENTIFIER)"
  minimum_ios="$(setting IPHONEOS_DEPLOYMENT_TARGET)"
  marketing_version="$(setting MARKETING_VERSION)"
  build_number="$(setting CURRENT_PROJECT_VERSION)"
  info_plist_setting="$(setting INFOPLIST_FILE)"
  debug_information="$(setting DEBUG_INFORMATION_FORMAT)"
  swift_version="$(setting SWIFT_VERSION)"
  development_team="$(setting DEVELOPMENT_TEAM)"
  code_sign_style="$(setting CODE_SIGN_STYLE)"

  if [[ "$target_name" == "PatientApp" ]]; then
    pass "Release scheme resolves the PatientApp target"
  else
    fail "Release scheme target is '${target_name:-unset}', expected PatientApp"
  fi

  if [[ "$bundle_id" =~ ^[A-Za-z0-9][A-Za-z0-9.-]+$ ]]; then
    pass "Bundle identifier is valid: $bundle_id"
  else
    fail "Bundle identifier is missing or invalid: '${bundle_id:-unset}'"
  fi
  if [[ -n "$expected_bundle_id" && "$bundle_id" != "$expected_bundle_id" ]]; then
    fail "Bundle identifier '$bundle_id' does not match IOS_EXPECTED_BUNDLE_ID '$expected_bundle_id'"
  fi
  if [[ "$bundle_id" == com.example.* ]]; then
    warn "Bundle identifier uses the checked-in example prefix; configure IOS_EXPECTED_BUNDLE_ID before TestFlight"
  fi

  if [[ "$minimum_ios" =~ ^[0-9]+\.[0-9]+$ ]]; then
    pass "Minimum iOS version is set: $minimum_ios"
  else
    fail "Minimum iOS version is missing or invalid: '${minimum_ios:-unset}'"
  fi
  if [[ "$marketing_version" =~ ^[0-9]+\.[0-9]+(\.[0-9]+)?([.-][0-9A-Za-z.-]+)?$ ]]; then
    pass "Marketing version is valid: $marketing_version"
  else
    fail "Marketing version is missing or invalid: '${marketing_version:-unset}'"
  fi
  if [[ "$build_number" =~ ^[1-9][0-9]*$ ]]; then
    pass "Build number is valid: $build_number"
  else
    fail "Build number is missing or invalid: '${build_number:-unset}'"
  fi
  if [[ -n "$expected_marketing_version" && "$marketing_version" != "$expected_marketing_version" ]]; then
    fail "Marketing version '$marketing_version' does not match IOS_EXPECTED_MARKETING_VERSION '$expected_marketing_version'"
  fi
  if [[ -n "$expected_build_number" && "$build_number" != "$expected_build_number" ]]; then
    fail "Build number '$build_number' does not match IOS_EXPECTED_BUILD_NUMBER '$expected_build_number'"
  fi

  if [[ "$debug_information" == "dwarf-with-dsym" ]]; then
    pass "Release debug information produces dSYMs"
  else
    fail "Release DEBUG_INFORMATION_FORMAT is '${debug_information:-unset}', expected dwarf-with-dsym"
  fi
  if [[ "$swift_version" == "6.0" ]]; then
    pass "Release Swift version is 6.0"
  else
    warn "Release Swift version is '${swift_version:-unset}'"
  fi

  if [[ -n "$info_plist_setting" ]]; then
    info_plist="$(cd "$repo_root/apps/ios" && realpath "$info_plist_setting" 2>/dev/null || true)"
  else
    info_plist=""
  fi
  if [[ -z "$info_plist" || ! -f "$info_plist" ]]; then
    fail "Release INFOPLIST_FILE does not resolve to a file: '${info_plist_setting:-unset}'"
  else
    relative_info_plist="${info_plist#"$repo_root"/}"
    pass "Release Info.plist resolves: $relative_info_plist"
    required_plist_keys=(NSCameraUsageDescription NSPhotoLibraryUsageDescription NSPhotoLibraryAddUsageDescription)
    for key in "${required_plist_keys[@]}"; do
      value="$(plist_value "$key")"
      if [[ -n "${value//[[:space:]]/}" ]]; then
        pass "Info.plist privacy key is present: $key"
      else
        fail "Info.plist privacy key is missing or empty: $key"
      fi
    done
    background_mode_processing="$(/usr/libexec/PlistBuddy -c 'Print :UIBackgroundModes:0' "$info_plist" 2>/dev/null || true)"
    if [[ "$background_mode_processing" == "processing" ]]; then
      pass "Info.plist enables background processing"
    else
      fail "Info.plist UIBackgroundModes does not include processing"
    fi
    for key in CFBundleIdentifier CFBundleShortVersionString CFBundleVersion; do
      if [[ -n "$(plist_value "$key")" ]]; then
        pass "Info.plist bundle key is present: $key"
      else
        fail "Info.plist bundle key is missing: $key"
      fi
    done
    icon_name="$(plist_value CFBundleIconName)"
    if [[ "$icon_name" == "AppIcon" && -f "$repo_root/apps/ios/Resources/Assets.xcassets/AppIcon.appiconset/Contents.json" ]]; then
      pass "App icon asset catalog is configured"
    else
      fail "App icon asset catalog or CFBundleIconName is missing"
    fi
    permitted_task="$(/usr/libexec/PlistBuddy -c 'Print :BGTaskSchedulerPermittedIdentifiers:0' "$info_plist" 2>/dev/null || true)"
    if [[ "$permitted_task" == "patient-app.uploads" ]]; then
      pass "Background upload task identifier is declared"
    else
      fail "BGTaskSchedulerPermittedIdentifiers is missing patient-app.uploads"
    fi
    for orientation in UIInterfaceOrientationPortrait UIInterfaceOrientationPortraitUpsideDown UIInterfaceOrientationLandscapeLeft UIInterfaceOrientationLandscapeRight; do
      if /usr/libexec/PlistBuddy -c "Print :UISupportedInterfaceOrientations" "$info_plist" 2>/dev/null | grep -Fq "$orientation"; then
        continue
      fi
      fail "Info.plist is missing supported orientation: $orientation"
    done
  fi

  if [[ -n "$development_team" && -n "$code_sign_style" ]]; then
    pass "Release signing settings are configured (team and style present)"
  elif is_true "$require_signing"; then
    fail "Release signing is required but DEVELOPMENT_TEAM or CODE_SIGN_STYLE is unset"
  else
    warn "Release signing is host-configured; DEVELOPMENT_TEAM/CODE_SIGN_STYLE are not checked-in"
  fi
fi

privacy_manifest="$repo_root/apps/ios/Resources/PrivacyInfo.xcprivacy"
if [[ -f "$privacy_manifest" ]]; then
  pass "Privacy manifest exists"
else
  fail "Privacy manifest is missing: $privacy_manifest"
fi

if [[ -f "$crash_monitoring_config" ]]; then
  if grep -Fq '"release_identifier"' "$crash_monitoring_config" && \
     grep -Fq '"upload_dsyms": true' "$crash_monitoring_config" && \
     grep -Fq '"collects_phi": false' "$crash_monitoring_config"; then
    pass "Crash monitoring placeholder is present and PHI-safe"
  else
    fail "Crash monitoring config is missing release, dSYM, or PHI-safety fields: $crash_monitoring_config"
  fi
else
  fail "Crash monitoring config is missing: $crash_monitoring_config"
fi

if ((${#failures[@]} > 0)); then
  echo
  echo "Preflight failed with ${#failures[@]} blocking issue(s):" >&2
  printf ' - %s\n' "${failures[@]}" >&2
  exit 1
fi

echo
if ((${#warnings[@]} > 0)); then
  echo "Preflight passed with ${#warnings[@]} warning(s)."
else
  echo "Preflight passed with no warnings."
fi
