#!/usr/bin/env bash
set -euo pipefail

ios_root="${1:-apps/ios}"
if [[ ! -d "$ios_root" ]] || ! find "$ios_root" -type f -not -name .gitkeep -print -quit | grep -q .; then
  echo "Skipping iOS tests: $ios_root is not present yet."
  exit 0
fi

package_file="$(find "$ios_root" -type f -name Package.swift -not -path './.git/*' -not -path '*/.build/*' -not -path '*/Packages/*' -not -path '*/.swiftpm/*' -print -quit)"
if [[ -n "$package_file" ]]; then
  package_dir="$(dirname "$package_file")"
  echo "Running Swift package tests in $package_dir..."
  (cd "$package_dir" && swift test)
  exit 0
fi

workspace="$(find "$ios_root" -maxdepth 5 -type d -name '*.xcworkspace' -print -quit)"
project="$(find "$ios_root" -maxdepth 5 -type d -name '*.xcodeproj' -print -quit)"

if [[ -z "$workspace" && -z "$project" ]]; then
  echo "Skipping iOS tests: no Swift package, Xcode project, or workspace is present under $ios_root yet."
  exit 0
fi

if [[ -z "${IOS_SCHEME:-}" ]]; then
  echo "IOS_SCHEME must be set when an Xcode project or workspace is present." >&2
  exit 1
fi

if [[ -n "$workspace" ]]; then
  xcodebuild -workspace "$workspace" -scheme "$IOS_SCHEME" -destination 'platform=iOS Simulator,name=iPhone 16' test
else
  xcodebuild -project "$project" -scheme "$IOS_SCHEME" -destination 'platform=iOS Simulator,name=iPhone 16' test
fi
