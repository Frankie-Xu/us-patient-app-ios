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
- `PatientAppTests` scheme XCTest run: passed, 51 UI/model tests, 0 failures, on the booted iPhone 18 Pro Simulator.
- The shared `PatientAppDomain` scheme now has an explicit Test action; its Xcode XCTest run passed 63 domain tests with 0 failures on the same Simulator.
- The app bundle installed and launched on the booted iPhone 18 Pro Simulator; see `patient-app-home.png`.
- Demo-only `--patient-app-demo-signed-in` launch reaches Home; see `patient-app-demo-home.png`.
- Demo-only `--patient-app-demo-signed-in --patient-app-demo-imported` launch reaches the imported-record state with one reviewable fact; see `patient-app-demo-imported.png`.
- The rebuilt app was reinstalled and relaunched with the same deterministic arguments; see `patient-app-demo-imported-final.png`.
- The review-gated path now exposes Doctor brief, visit questions, PDF export, document share and revoke actions from confirmed facts; the deterministic Home launch was rechecked after the change; see `patient-app-demo-imported-visit-brief.png`.
- Records now open a document detail view with processing status, version metadata, source guidance, fact review, and version-history navigation; the latest deterministic build was installed and launched again; see `patient-app-demo-record-detail.png`.
- The local URLSession fixture now completes review, PDF export, document share, status lookup, and revoke through the authenticated client; the latest launch was reinstalled after this flow was validated; see `patient-app-phase43-fixture.png`.
- The fixture state resets per runtime and returns contract-aligned 201/202 write responses; a regression test confirms a fresh runtime starts with an unconfirmed fact.
- Document and visit share surfaces now show active, expired, revoked, refreshing, and failed access states, with retry and revoke controls gated by status.
- Share status regression coverage now verifies active, expired, and revoked payload decoding plus 401, 403, and 404 error mapping.
- The latest Debug build was installed and launched on the booted iPhone 18 Pro Simulator with the deterministic fixture; see `patient-app-phase45-final.png`.
- The latest phase46 Debug build was reinstalled and launched on the booted iPhone 18 Pro Simulator; see `patient-app-phase46-final.png`.
- `scripts/ios-release-preflight.sh`: passed with two expected local warnings; strict signing mode correctly fails until a distribution bundle ID, development team, and signing style are configured.
- `scripts/test-ios-release-preflight.sh`: passed with deterministic default, bundle/version mismatch, and strict-signing cases.
- SwiftPM PatientAppUI build: passed.
- SwiftPM tests: 114 tests passed (63 Domain + 51 UI/model).
- `scripts/check-contract-drift.sh`: passed with the current 19-route inventory, including the strict PyYAML-free fallback used on hosts without the optional parser dependency.
- `scripts/test-contract-drift.sh`: passed, including mutation and malformed-fallback regressions.
- `bash scripts/validate-repo.sh`: passed.
- `git diff --check`: passed.
- Simulator boot and `simctl io screenshot`: passed; see `iphone18pro-boot.png`.

## Contract follow-up

- The checked-in 19-route inventory now passes locally without requiring PyYAML; the fallback parser accepts only the repository's reviewed OpenAPI layout and fails closed on malformed input.
- API PR #71 remains a separate broader contract follow-up for owner-scoped share status and PDF export. It is not auto-merged by this validation pass.

## Managed-host limitations

- An unprivileged `xcodebuild` UI/app invocation can reject `sandbox-exec` with `sandbox_apply: Operation not permitted`; the approved host invocation compiles PatientAppUI and the PatientApp target successfully.
- The scheme-level test crash was traced to the generated scheme XML. The generator now emits the canonical Xcode 27 test action shape (explicit build targets, macro expansion, testables, launch/profile runnables), and the approved host runs the full test scheme successfully.
- Unprivileged Xcode invocations can still lose access to CoreSimulator (`CoreSimulatorService connection became invalid`); approved host access is required for Simulator builds and XCTest execution in this managed environment.
