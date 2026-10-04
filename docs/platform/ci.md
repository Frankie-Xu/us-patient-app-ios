# Platform CI and merge gates

The repository CI is intentionally credential-free. Every job uses read-only repository access, checkout credentials are removed, and no deployment or cloud resource is created.

## Required pull request checks

Configure branch protection on `main` to require these exact check names:

- **Repository validation** — repository policy scan, dependency manifest/version checks, workflow action pin checks, scanner regression tests, and patch formatting.
- **Contract validation** — OpenAPI 3.x and JSON Schema parsing plus internal reference checks. The job succeeds with an explicit skip message while `packages/contracts` has no contract files.
- **API tests** — discovers `services/api` Python tests and runs them with the pinned `pytest` tool. It skips only when the component or its tests are absent.
- **AI tests** — applies the same discovery rules to `services/ai`.
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
bash scripts/run-python-tests.sh services/api
bash scripts/run-python-tests.sh services/ai
bash scripts/run-ios-tests.sh apps/ios
```
