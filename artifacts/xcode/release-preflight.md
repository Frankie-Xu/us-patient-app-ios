# iOS Release/TestFlight preflight

The read-only preflight is [scripts/ios-release-preflight.sh](../../scripts/ios-release-preflight.sh). It resolves the checked-in Xcode project and Release settings before an archive or TestFlight upload. It does not change versions, signing settings, project files, or source code.

## Validation run

Run from the repository root on 2026-10-05:

```sh
scripts/ios-release-preflight.sh
```

The current host passed with two expected warnings:

- Xcode 27.0 is available and `PatientApp.xcodeproj` resolves successfully.
- `PatientApp-Debug` is available for the Release configuration and `PatientAppTests` is available for tests.
- The app target is `PatientApp` with bundle identifier `com.example.patientapp`.
- Minimum iOS version is 17.0; marketing version is 0.1.0; build number is 1.
- Release debug information is `dwarf-with-dsym` and Swift version is 6.0.
- `Resources/Info.plist` resolves and contains camera, photo-library, background-processing, and bundle version keys.
- `Resources/PrivacyInfo.xcprivacy` is present.
- `artifacts/xcode/crash-monitoring.example.json` is present with a release
  identifier, dSYM upload requirement, and `collects_phi: false`. Replace the
  provider and inject its DSN only through CI secrets before distribution.
- Warning: `com.example.patientapp` is the checked-in local example identifier. Set `IOS_EXPECTED_BUNDLE_ID` for a distribution identifier before uploading.
- Warning: `DEVELOPMENT_TEAM` and `CODE_SIGN_STYLE` are host-configured and are intentionally not committed.

To make signing configuration a blocking check on a distribution runner, set:

```sh
IOS_PREFLIGHT_REQUIRE_SIGNING=1 \
IOS_EXPECTED_BUNDLE_ID=com.example.patientapp.production \
scripts/ios-release-preflight.sh
```

The strict signing mode was also exercised on the current host and correctly returned status 1 because no development team or signing style is checked in. That is an expected local limitation, not a source or project validation failure.

The parameter and failure paths are covered without a real Xcode installation by:

```sh
scripts/test-ios-release-preflight.sh
```

The offline regression uses a deterministic `xcodebuild` shim and verifies that the default configuration passes, bundle/version assertions fail with both messages, and `IOS_PREFLIGHT_REQUIRE_SIGNING=1` blocks an unsigned host. The regression completed successfully on the same date.

Optional environment variables allow CI to pin the intended release inputs without changing the script:

| Variable | Default | Purpose |
| --- | --- | --- |
| `IOS_PROJECT` | `apps/ios/PatientApp.xcodeproj` | Xcode project path |
| `IOS_RELEASE_SCHEME` | `PatientApp-Debug` | Scheme used for Release settings |
| `IOS_RELEASE_CONFIGURATION` | `Release` | Configuration to inspect |
| `IOS_TEST_SCHEME` | `PatientAppTests` | Test scheme that must exist |
| `IOS_EXPECTED_BUNDLE_ID` | unset | Distribution bundle identifier assertion |
| `IOS_EXPECTED_MARKETING_VERSION` | unset | Version assertion |
| `IOS_EXPECTED_BUILD_NUMBER` | unset | Build number assertion |
| `IOS_PREFLIGHT_REQUIRE_SIGNING` | `0` | Make host signing settings blocking |
| `IOS_CRASH_MONITORING_CONFIG` | `artifacts/xcode/crash-monitoring.example.json` | Crash monitoring config to validate |
