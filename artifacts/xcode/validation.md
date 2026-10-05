# Xcode toolchain validation (synthetic, no PHI)

- Date: 2026-10-05
- Follow-up validation: 2026-10-06 (Asia/Singapore)
- Current follow-up run: `xcodebuild` Debug build, Release build, and `PatientAppTests` XCTest all passed on the booted simulator; a fresh no-PHI screenshot was saved under `/tmp/patient-app-simulator-regression-20261006.png`.
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
- Release archive: passed with `CODE_SIGNING_ALLOWED=NO` at `/tmp/patientapp-release-no-sign.xcarchive`; the archive generated the app dSYM. Distribution signing remains unverified.
- `PatientAppTests` scheme XCTest run: passed, 72 domain tests + 51 UI/model tests + 2 XCUIApplication UI tests (125 total), 0 failures, on the booted iPhone 18 Pro Simulator. The latest run includes signed-out login controls and deterministic Home → Import → Review navigation, with a screenshot attachment retained in `/tmp/patientapp-full-final3.xcresult`.
- The shared `PatientAppDomain` scheme has an explicit Test action; the domain tests are included in the 72-test result above.
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
- Phase47 corrected upload/processing status presentation, removed duplicate background queue insertion for imports, and added stable accessibility identifiers for the primary tabs, upload progress, and fact list; the latest Debug build was installed and launched; see `patient-app-phase47-final.png`.
- `scripts/ios-release-preflight.sh`: passed with two expected local warnings; strict signing mode correctly fails until a distribution bundle ID, development team, and signing style are configured.
- `scripts/test-ios-release-preflight.sh`: passed with deterministic default, bundle/version mismatch, strict-signing, and missing crash-monitoring configuration cases.
- The release checklist and PHI-safe crash-monitoring placeholder are checked in under `artifacts/xcode/`; no DSN or signing material is committed.
- SwiftPM PatientAppUI build: passed.
- SwiftPM `swift test --package-path apps/ios`: passed with 72 XCTest cases in the domain test target; the authoritative app/UI validation remains the Xcode result bundle above.
- `bash scripts/staging/test-smoke.sh`: passed for upload → OCR → fact review → doctor brief → PDF → share → revoke, including dependency retry, idempotency, version conflict, and post-revoke denial.
- API tests: 87 passed, including signed local JWT session/refresh/logout rotation, checksum deduplication, the queue worker pipeline, and the server-side Qwen OCR boundary (key format/endpoint/model validation, key isolation, retryable 429/5xx/network classification, terminal 4xx classification, empty/non-JSON handling, bounded PDF rasterization, and terminal rasterizer failures).
- Worker/provider checks: worker pipeline, queue, and retry-policy tests passed. The queue consumer has bounded exponential retry backoff, lease recovery, idempotent acknowledgement, and an explicit metadata-write race retry.
- AI tests: 59 passed, including 7 deterministic staging-adapter tests covering OCR normalization, bilingual de-identified fixtures, source spans, low-confidence/conflict gates, explicit review, summary provider replacement, and model/latency/cost reporting.
- `scripts/run-ai-staging-regression.sh`: passed for 3 de-identified cases; report records model version, latency, cost, conflict count, missing spans, and blocked delivery.
- `scripts/check-contract-drift.sh`: passed with the current 19-route inventory, including the strict PyYAML-free fallback used on hosts without the optional parser dependency.
- `scripts/test-contract-drift.sh`: passed, including mutation and malformed-fallback regressions.
- `bash scripts/validate-repo.sh`: passed.
- `git diff --check`: passed.
- Simulator boot and `simctl io screenshot`: passed; see `iphone18pro-boot.png`.

## Real staging composition

- This report records the current worktree and live run; no historical commit IDs are used as evidence for this round.
- Local Docker runtime: Colima 0.10.3 with Docker Engine 29.5.2, Docker Compose 5.5.1, and Buildx 0.37.2 on arm64.
- Docker Hub access uses a VM-local loopback tunnel to the existing host proxy; the host proxy listener remains loopback-only.
- `docker compose --env-file .env.staging.example -f infra/staging/compose.yaml config --quiet`: passed.
- `scripts/staging/test-compose.sh`: passed.
- Provider adapter unit tests: 9 passed; Qwen3.5-OCR boundary tests: 5 passed; the current API test suite reported 79 tests passed.
- The rebuilt staging Worker image includes `poppler-utils`; `/usr/bin/pdftoppm` was present in the container, and a synthetic one-page PDF rasterized to PNG without a provider call. This rasterization check is independent of the external OCR provider.
- Bailian configuration was supplied locally through the hidden-input helper. The US Virginia workspace endpoint is stored only in ignored `.env.staging`; the Key is present there with owner-only permissions and is not recorded in artifacts. The live Worker now reports `queue-consumer-qwen-vl-ocr` with `consumer_enabled=true` and `data_classification=deidentified`.
- A host-side HTTPS smoke request using the configured endpoint and a synthetic text image succeeded with `qwen-vl-ocr` (text length 18 and the synthetic marker detected). The same request with `qwen3.5-ocr` returned provider `model_not_found`; US Virginia currently uses the `qwen-vl-ocr` fallback.
- The Worker receives proxy settings only from ignored `.env.staging` variables and resolves the Docker host through `host.docker.internal`; the proxy address is not tracked. A container-side synthetic image request completed with `qwen-vl-ocr` (text length 18 and marker detected), so the local provider path is verified without using PHI. The Worker does not silently fall back to fixtures.
- The API image installs the PostgreSQL, S3-compatible, and Redis clients and starts through `scripts/staging/api_entrypoint.py`; startup applies the PostgreSQL migration and fails closed when a required provider is unavailable.
- Live local staging now passes: PostgreSQL, the pinned LocalStack-compatible S3 persistence image, Redis, API, and worker are healthy; `/readyz` reports all three API dependencies ready.
- A synthetic 35-byte document was persisted through the API, uploaded to S3, queued in Redis, and replayed with the same idempotency key without creating a duplicate job.
- Provider-backed HTTP checks passed for duplicate document/job submission, fact version conflict (`409`), fact confirmation, share access, revoke denial (`410`), and short-TTL expiry denial (`410`).
- Redis failure injection passed: stopping Redis made API `/readyz` fail as expected, restarting Redis restored API/worker readiness, and the synthetic queue recovered without leaving an unacknowledged metadata-only job.
- The earlier live HTTP acceptance run used `queue-consumer-fixture-ocr`; a synthetic text upload was consumed from Redis, persisted as a ready document, and produced an unreviewed source-located fact. That evidence is fixture text ingest, not provider OCR or model inference. The current configured Worker uses `queue-consumer-qwen-vl-ocr`; the provider-backed image path is now verified through the container host-gateway proxy. Missing local `pdftotext`/`tesseract` providers fail explicitly instead of being reported as OCR success.
- Live HTTP acceptance passed upload, same-key idempotency, account-scoped checksum deduplication, queue processing with provider OCR, source spans, manual fact review, stale version conflict, share access, expiry, revoke denial, and audit history. Doctor brief, visit questions, and PDF export remain deterministic fixture projections because the current HTTP contract has no routes for them. The report is saved at `artifacts/staging/integration-acceptance-report.json`.
- The explicit retention check preserved PostgreSQL metadata and the uploaded object after restarting PostgreSQL, the S3 service, Redis, API, and Worker. It verified the object checksum metadata and read-back bytes.
- A loopback-only HTTPS staging proxy is now available through `scripts/staging/start-local-https.sh` and `scripts/staging/local_https_proxy.py`. It generated a 30-day test CA under `/tmp`, the CA was installed into the booted iPhone 18 Pro Simulator with `simctl keychain`, and `curl --cacert` reached `/readyz` over `https://127.0.0.1:58443`. The proxy is test-only and forwards to the local API; it does not provide remote staging or production trust.
- The staging-parameter Simulator launch completed with the HTTPS URL and saved `patientapp-staging-live-configuration.png`; no production URL, token, or credential was embedded.
- The local API now issues and verifies signed development JWTs with refresh rotation; external OAuth/JWT issuer integration, remote HTTPS staging, and TestFlight distribution signing are not configured on this host. XCTest and explicit deterministic launches use the fixture boundary; staging runtime configuration does not silently fall back when an HTTPS URL is invalid.
- The checked-in `.env.staging.example` contains placeholder credentials only. A remote staging run still requires an approved HTTPS API endpoint, secret-manager references for provider credentials, and an identity issuer/audience; no production credential or PHI is stored here.

## Contract follow-up

- The checked-in 19-route inventory now passes locally without requiring PyYAML; the fallback parser accepts only the repository's reviewed OpenAPI layout and fails closed on malformed input.
- API PR #71 remains a separate broader contract follow-up for owner-scoped share status and PDF export. It is not auto-merged by this validation pass.

## Managed-host limitations

- An unprivileged `xcodebuild` UI/app invocation can reject `sandbox-exec` with `sandbox_apply: Operation not permitted`; the approved host invocation compiles PatientAppUI and the PatientApp target successfully.
- The scheme-level test crash was traced to the generated scheme XML. The generator now emits the canonical Xcode 27 test action shape (explicit build targets, macro expansion, testables, launch/profile runnables), and the approved host runs the full test scheme successfully.
- Unprivileged Xcode invocations can still lose access to CoreSimulator (`CoreSimulatorService connection became invalid`); approved host access is required for Simulator builds and XCTest execution in this managed environment.
- The current managed Python host enforces PEP 668 and has no network access for installing service dependencies; the scoped staging agent ran API 54/54 and AI 59/59 in its pinned test environment. Local `run-python-tests.sh` reruns require the CI dependency environment.

## 2026-10-06 Simulator follow-up (Step 6)

- `xcodebuild -list` passed and exposed `PatientApp-Debug`, `PatientAppTests`, `PatientAppDomain`, and `PatientAppUI` schemes.
- Fresh `PatientAppTests` Debug run passed 126 tests with 0 failures: 72 domain tests, 51 UI/model tests, and 3 XCUIApplication launch-flow tests.
- The new XCUIApplication flow drove synthetic Home → Import → Upload/processing → Record detail → Fact review → Doctor brief → Visit questions → PDF export → Share → Revoke, with no PHI.
- Fresh `PatientApp-Debug` Debug and Release Simulator builds passed with signing disabled.
- The Debug app was installed and launched on the booted iPhone 18 Pro Simulator with the deterministic signed-in argument. Screenshot evidence is stored at `artifacts/xcode/simulator-flow-20261006.png`; the machine-readable record is `artifacts/xcode/simulator-flow-20261006.json`.
- External remote staging, OAuth/JWT issuer configuration, Apple Team signing, and TestFlight publishing remain unverified and are intentionally not reported as complete.
