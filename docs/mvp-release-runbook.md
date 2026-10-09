# Patient App MVP release runbook

This runbook keeps the MVP path short and repeatable. It is intended for
synthetic or de-identified staging data and a deterministic TestFlight demo.
Advanced security review, enterprise identity, FHIR integration, billing, and
production PHI approval remain separate follow-up work.

## MVP acceptance path

The demo must complete this path without a hidden fallback:

1. Sign in with the selected fixture or staging session.
2. Import a PDF, photo, or synthetic record.
3. Show upload progress, retry, and cancellation states.
4. Open the record detail and version history.
5. Review facts, confidence, source spans, and conflicts.
6. Open the doctor brief and visit questions.
7. Export/share the record, then revoke the share.

The app defaults to deterministic fixture data. Staging is opt-in through an
HTTPS base URL supplied at launch; an invalid staging configuration is shown to
the user and never silently becomes a live session.

## Minimum release gate

Only these checks block the MVP build:

- no committed API keys, bearer tokens, PHI, or production URLs;
- staging uses HTTPS and server-side provider credentials;
- the upload queue is retryable and idempotent;
- low-confidence, missing-source, or conflicting facts require review;
- share links can expire and be revoked;
- Release builds have privacy descriptions, a privacy manifest, dSYMs, and a
  configured bundle identifier before external distribution.

Deep penetration testing, enterprise SSO, formal compliance evidence, and
long-term incident exercises are tracked separately and do not block the
synthetic MVP demo.

## Staging lifecycle

Keep `.env.staging` and provider secrets outside Git with owner-only
permissions. Never use `--volumes` for a normal stop.

```sh
scripts/staging/compose-up.sh
scripts/staging/compose-health.sh
scripts/staging/run-smoke.sh artifacts/staging/staging-smoke-report.json
```

To pause the environment, stop the ECS instance normally or run:

```sh
scripts/staging/compose-down.sh
```

The latter keeps named volumes. On resume, run `compose-up.sh`, health checks,
and the smoke test before pointing a Simulator at staging. If the ECS fixed
public IP changes after an economical stop, update the HTTPS endpoint before
launching the app.

## iOS validation

Run the release preflight, then build and test the shared Xcode project:

```sh
bash scripts/ios-release-preflight.sh
xcodebuild -project apps/ios/PatientApp.xcodeproj \
  -scheme PatientApp-Debug -configuration Release \
  -sdk iphonesimulator build
xcodebuild test -project apps/ios/PatientApp.xcodeproj \
  -scheme PatientAppTests -destination 'platform=iOS Simulator'
```

The registered App ID is `com.johannisxu.uspatientapp` for Team ID
`QH6389JMZY`; the Xcode project and release-preflight fixture use that value.
Keep signing certificates, export options, and App Store Connect secrets only
in the CI/host secret store immediately before a signed archive.

## TestFlight handoff

1. Set the production bundle identifier and Apple Team in the host/CI secret
   store.
2. Run the Release archive and export without enabling upload.
3. Inspect the IPA, dSYMs, privacy manifest, permissions, and version number.
4. Enable upload only for an intentional TestFlight run.
5. Invite internal testers after App Store Connect processing completes.

No step in this runbook publishes automatically or merges a pull request.
