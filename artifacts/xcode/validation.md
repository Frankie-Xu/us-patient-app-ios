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
- `PatientAppTests` scheme XCTest run: passed, 51 UI/model tests, 0 failures, on the booted iPhone 18 Pro Simulator; the SwiftPM suite below covers 61 domain tests as well.
- The app bundle installed and launched on the booted iPhone 18 Pro Simulator; see `patient-app-home.png`.
- Demo-only `--patient-app-demo-signed-in` launch reaches Home; see `patient-app-demo-home.png`.
- Demo-only `--patient-app-demo-signed-in --patient-app-demo-imported` launch reaches the imported-record state with one reviewable fact; see `patient-app-demo-imported.png`.
- The rebuilt app was reinstalled and relaunched with the same deterministic arguments; see `patient-app-demo-imported-final.png`.
- The review-gated path now exposes Doctor brief, visit questions, PDF export, document share and revoke actions from confirmed facts; the deterministic Home launch was rechecked after the change; see `patient-app-demo-imported-visit-brief.png`.
- Records now open a document detail view with processing status, version metadata, source guidance, fact review, and version-history navigation; the latest deterministic build was installed and launched again; see `patient-app-demo-record-detail.png`.
- The local URLSession fixture now completes review, PDF export, document share, status lookup, and revoke through the authenticated client; the latest launch was reinstalled after this flow was validated; see `patient-app-phase43-fixture.png`.
- The fixture state resets per runtime and returns contract-aligned 201/202 write responses; a regression test confirms a fresh runtime starts with an unconfirmed fact.
- Document and visit share surfaces now show active, expired, revoked, refreshing, and failed access states, with retry and revoke controls gated by status.
- The latest Debug build was installed and launched on the booted iPhone 18 Pro Simulator with the deterministic fixture; see `patient-app-phase45-final.png`.
- `scripts/ios-release-preflight.sh`: passed with two expected local warnings; strict signing mode correctly fails until a distribution bundle ID, development team, and signing style are configured.
- SwiftPM PatientAppUI build: passed.
- SwiftPM tests: 112 tests passed (61 Domain + 51 UI/model).
- `bash scripts/validate-repo.sh`: passed.
- `git diff --check`: passed.
- Simulator boot and `simctl io screenshot`: passed; see `iphone18pro-boot.png`.

## Contract follow-up

- The current base contract inventory does not yet include owner-scoped `GET /v1/shares/{shareId}`. The iOS client keeps that route because API PR #71 adds the matching operation while preserving `/v1/shared/{token}` for public access. Re-run `scripts/check-contract-drift.sh` and the share status error mapping after PR #71 is integrated.

## Managed-host limitations

- An unprivileged `xcodebuild` UI/app invocation can reject `sandbox-exec` with `sandbox_apply: Operation not permitted`; the approved host invocation compiles PatientAppUI and the PatientApp target successfully.
- The scheme-level test crash was traced to the generated scheme XML. The generator now emits the canonical Xcode 27 test action shape (explicit build targets, macro expansion, testables, launch/profile runnables), and the approved host runs the full test scheme successfully.
- Unprivileged Xcode invocations can still lose access to CoreSimulator (`CoreSimulatorService connection became invalid`); approved host access is required for Simulator builds and XCTest execution in this managed environment.
