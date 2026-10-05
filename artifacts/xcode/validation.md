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
- PatientAppUI framework and PatientApp Debug app target builds: passed with approved Xcode host access.
- PatientApp Release app target build: passed with signing disabled.
- `PatientApp-Debug` Debug and Release app scheme builds: passed with signing disabled.
- `PatientAppTests` scheme XCTest run: passed, 101 tests (61 domain + 40 UI/model), 0 failures, on the booted iPhone 18 Pro Simulator.
- The app bundle installed and launched on the booted iPhone 18 Pro Simulator; see `patient-app-home.png`.
- Demo-only `--patient-app-demo-signed-in` launch reaches Home; see `patient-app-demo-home.png`.
- Demo-only `--patient-app-demo-signed-in --patient-app-demo-imported` launch reaches the imported-record state with one reviewable fact; see `patient-app-demo-imported.png`.
- The rebuilt app was reinstalled and relaunched with the same deterministic arguments; see `patient-app-demo-imported-final.png`.
- SwiftPM PatientAppUI build: passed.
- SwiftPM tests: 101 tests passed (Domain + UI).
- `bash scripts/validate-repo.sh`: passed.
- `git diff --check`: passed.
- Simulator boot and `simctl io screenshot`: passed; see `iphone18pro-boot.png`.

## Managed-host limitations

- An unprivileged `xcodebuild` UI/app invocation can reject `sandbox-exec` with `sandbox_apply: Operation not permitted`; the approved host invocation compiles PatientAppUI and the PatientApp target successfully.
- The scheme-level test crash was traced to the generated scheme XML. The generator now emits the canonical Xcode 27 test action shape (explicit build targets, macro expansion, testables, launch/profile runnables), and the approved host runs the full test scheme successfully.
- Unprivileged Xcode invocations can still lose access to CoreSimulator (`CoreSimulatorService connection became invalid`); approved host access is required for Simulator builds and XCTest execution in this managed environment.
