# Xcode toolchain validation (synthetic, no PHI)

- Date: 2026-10-05
- Xcode: 27.0 (27A266a)
- iOS SDK: 27.0
- iOS Simulator runtime: 27.0 (24A434)
- Device: iPhone 18 Pro (`39E5F9B7-5C5B-477B-B573-725920F120A3`)
- Deployment target: iOS 17.0
- Bundle identifier: `com.example.patientapp`
- Project: `apps/ios/PatientApp.xcodeproj`
- Schemes: `PatientApp-Debug`, `PatientAppTests`, `PatientAppDomain`, `PatientAppUI`

## Results

- `xcodebuild -list`: passed.
- PatientAppDomain Debug simulator build: passed.
- PatientAppDomain Release simulator build: passed.
- The domain XCTest target was attempted with `xcodebuild`; the managed host rejected its Clang module session path before compilation.
- SwiftPM PatientAppUI build: passed.
- SwiftPM tests: 101 tests passed (Domain + UI).
- `bash scripts/validate-repo.sh`: passed.
- `git diff --check`: passed.
- Simulator boot and `simctl io screenshot`: passed; see `iphone18pro-boot.png`.

## Managed-host limitations

- `xcodebuild` UI/app compilation cannot start SwiftUI macros because the managed host rejects `sandbox-exec` with `sandbox_apply: Operation not permitted`; Xcode reports `SwiftUIMacros.StateMacro` malformed response.
- `xcodebuild test` and `build-for-testing` cannot initialize CoreSimulator from the unprivileged process (`CoreSimulatorService connection became invalid`, `simdiskimaged ... not registered`, exit 139). The same iOS 27.0 simulator boots successfully through the approved Simulator command path above.
