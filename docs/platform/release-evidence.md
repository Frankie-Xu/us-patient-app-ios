# Release evidence manifest

`scripts/release_evidence.py` creates a machine-readable manifest for a release decision. It records only the commit SHA, workflow name/version/run identifiers, generation time, and aggregate statuses for repository, contract, API, AI and iOS checks. It never serializes command lines, working directories, file names, command output, request data, PHI or credentials.

## CI usage

The `release-evidence` job runs after the five component jobs and consumes their GitHub Actions result values through environment variables. It writes `artifacts/release-evidence.json` and uploads it with a short retention period. The manifest is useful when a job is skipped: `skipped` is explicit and does not pretend that a component ran.

A failed or cancelled component is recorded as `failed`. The script still writes the manifest and exits with status 1, so the artifact is available for diagnosis while the workflow remains fail-closed. Missing or malformed component status values also become `failed`.

## Local usage

Run the same checks locally with:

```text
python3 scripts/release_evidence.py --output artifacts/release-evidence.json
bash scripts/test-release-evidence.sh
```

Local mode runs the repository, contract, API, AI and available iOS checks while capturing their output in memory. Only status, exit code and duration are emitted. The regression test covers a passing manifest with an explicitly skipped iOS group and a failing repository group; it asserts that paths, PHI and token markers are absent.

The manifest is evidence of engineering checks. It does not approve production PHI, replace the production-boundary threat model, or create telemetry. Production decisions still require the controls and sign-off in the security ADR.
