# TestFlight release checklist

This checklist is for the first signed archive of the iOS patient app. It keeps
the deterministic local build usable while making distribution-only inputs
explicit.

## Before archiving

- Run `scripts/ios-release-preflight.sh` with the production bundle ID, marketing
  version, and build number assertions.
- Run `swift test --package-path apps/ios` and the Xcode `PatientAppTests` and
  `PatientAppDomain` schemes on the selected iOS Simulator.
- Confirm `Resources/Info.plist` contains camera, photo-library, background
  processing, and bundle version declarations.
- Confirm `Resources/PrivacyInfo.xcprivacy` is present and contains no tracking
  or collected-data declaration that has not been reviewed.
- Set the production bundle identifier, development team, and signing style in
  the CI host configuration; do not commit those values to the example project.

## Crash monitoring placeholder

The checked-in [crash monitoring example](crash-monitoring.example.json) is a
provider-neutral contract. Before inviting TestFlight testers, choose an
approved provider, inject its DSN through `CRASH_MONITORING_DSN`, and configure
the CI symbol upload step for the archive dSYMs. The release identifier must
match `CFBundleShortVersionString-CFBundleVersion`, and crash reports must not
collect PHI. Keep provider credentials and exported dSYM archives outside Git.

## Archive and upload

1. Set `IOS_XCODE_PROJECT`, `IOS_XCODE_SCHEME`, `IOS_EXPORT_OPTIONS`, and
   `APPLE_TEAM_ID` in the TestFlight workflow configuration.
2. Run the workflow with `IOS_TESTFLIGHT_UPLOAD` unset or `false` for a signed
   archive/export dry run.
3. Inspect the IPA, dSYM, privacy manifest, version, and release evidence.
4. Set `IOS_TESTFLIGHT_UPLOAD=true` only for an intentional App Store Connect
   upload, with the App Store Connect API key injected as ephemeral secrets.
5. Wait for App Store Connect processing and verify the build in TestFlight
   before inviting external testers.

The workflow never stores signing material, API keys, DSNs, or patient data in
the repository.
