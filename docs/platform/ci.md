# Platform CI and merge gates

The repository CI is intentionally credential-free. Every job uses read-only repository access, checkout credentials are removed, and no deployment or cloud resource is created.

## Required pull request checks

Configure branch protection on `main` to require these exact check names:

- **Repository validation** — repository policy scan, dependency manifest/version checks, workflow action pin checks, scanner regression tests, and patch formatting.
- **Contract validation** — OpenAPI 3.x and JSON Schema parsing plus internal reference checks. The job succeeds with an explicit skip message while `packages/contracts` has no contract files.
- **API tests** — discovers `services/api` Python tests, runs route tests in the same pinned `pytest` suite, performs an in-process `/healthz` readiness smoke without binding a port, and uploads a PHI-safe aggregate result JSON. It skips when the component or its tests are absent; the readiness result is also explicitly marked skipped until an app adapter exists.
- **AI tests** — emits an aggregate synthetic golden-set regression report, uploads the PHI-safe aggregate JSON, then applies the same discovery rules to `services/ai`.
- **iOS tests** — runs `apps/ios` Swift Package or Xcode tests when that component is present. The job is skipped when no iOS project or package exists yet.

A skipped component is an intentional green result for the scaffold. The pull request must state which component was skipped and why. Once a component and its tests land, the same check discovers and runs them; a failing test remains a failing check.

## Contract gate

Put OpenAPI YAML/JSON and JSON Schema files under `packages/contracts`. `scripts/check-openapi.sh` validates the OpenAPI 3.x top-level structure, required metadata, non-empty paths, components, JSON Schema shape, and every internal `#/...` reference. The checker uses the pinned Python tools in `scripts/requirements-ci.txt`, rejects duplicate keys and external references, and never calls an API or needs credentials.

## Workflow and dependency policy

All `uses:` references in `.github/workflows` must be full 40-character commit SHAs with a human-readable version comment. `scripts/check-workflow-pins.sh` enforces this, requires top-level `permissions:`, and requires `persist-credentials: false` whenever checkout is used. Dependabot is configured to propose weekly GitHub Actions updates.

`scripts/check-dependencies.sh` validates Swift package manifests, Node package metadata, and Python project metadata when those files are present. It reports the tool versions used by the check and does not install deployment tooling.

## Local commands

The Python gates use the pinned tools in `scripts/requirements-ci.txt`; install them in a disposable environment before running the contract or workflow-policy checks locally.

Run these before opening a pull request:

```text
bash scripts/validate-repo.sh
bash scripts/test-validate-repo.sh
bash scripts/check-dependencies.sh
bash scripts/check-workflow-pins.sh
bash scripts/check-openapi.sh
bash scripts/discover-http-route-tests.sh services/api
bash scripts/run-api-readiness.sh services/api
bash scripts/run-ai-golden-regression.sh services/ai
bash scripts/run-python-tests.sh services/api
bash scripts/run-python-tests.sh services/ai
bash scripts/run-ios-tests.sh apps/ios
```

## HTTP route smoke and test discovery

The API job runs the complete `services/api` test tree with the pinned `pytest` tool, then executes `scripts/run-api-readiness.sh services/api`. `scripts/discover-http-route-tests.sh` scans for a FastAPI/`APIRouter` adapter and reports test files that use `TestClient`, `ASGITransport`, `httpx`, an HTTP client call, or a health route. Any discovered route test remains part of the same failing test gate; the pytest runner suppresses tracebacks and captured output, and route discovery never prints request or response bodies. If the adapter exists before route tests land, CI reports the gap and still runs the service tests. The readiness smoke calls the adapter or FastAPI app factory in process and checks only the status shape; it never starts a public listener or prints a response body. The job uploads `artifacts/api-readiness.json` with status, HTTP status, and a fixed response-shape label only; upload uses `if-no-files-found: error` so an upload failure fails the job.

Route tests should construct the app in process and use synthetic requests. They should cover the health response, authentication and validation boundaries, status codes, idempotency or version headers where applicable, and PHI-safe error responses. They must not bind a public port, call a deployed service, require credentials, or log payloads.

## AI golden-set regression report

`scripts/run-ai-golden-regression.sh services/ai` loads the checked-in synthetic golden set when available, runs the deterministic stub pipeline, and logs only dataset version, case count, aggregate precision/recall/citation and review-required recall, blocking-error count, and the delivery-blocked flag. It fails when required aggregate safety metrics drop below 1.0 or the fixture cannot be loaded. Expected synthetic conflict blockers are reported as an aggregate and never print case text, claims, or document content. The job uploads `artifacts/ai-golden-regression.json`, containing only the aggregate metrics, status, dataset version, case count, blocker count, and delivery flag; it never uploads fixture text, claims, request bodies, patient data, or Swift build output.

## iOS polling and transport tests and SwiftPM cache behavior

The iOS job invokes `scripts/run-ios-tests.sh apps/ios`. It discovers `*Transport*Tests.swift`, `*APIClient*Tests.swift`, `*URLSession*Tests.swift`, `*Polling*Tests.swift`, and `*ContractAdapterTests.swift` files for an explicit log message, then runs the entire SwiftPM or Xcode test suite so those tests cannot be omitted by a narrow filter.

SwiftPM uses its default sandbox and a fresh macOS runner. The job does not persist `.build`, `Package.resolved`, derived data, simulator state, or dependency caches between pull requests. Keep those paths ignored and do not add cache restoration that could reuse artifacts from an untrusted pull request. Transport tests use deterministic mocks or local fixtures; no network endpoint, signing credential, or real patient data is available to the job.
