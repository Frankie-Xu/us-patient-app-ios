# Staging smoke evidence

The staging smoke uses the existing provider-neutral API runtime and the
deterministic AI golden fixture. It is a local/staging rehearsal; it does not
bind a port, call a model provider, use cloud credentials, or contain patient
records.

Run the repeatable check from the repository root:

```sh
bash scripts/staging/run-smoke.sh
```

The command writes `artifacts/staging/staging-smoke-report.json`. The regression
wrapper writes to a temporary report and validates the safety and failure
assertions without changing the checked-in evidence:

```sh
bash scripts/staging/test-smoke.sh
```

The flow uses the current API and AI boundaries without adding routes or
duplicating transport logic:

1. SQLite metadata, object-store, and queue readiness.
2. Document and upload-session creation, idempotent replay, object-store
   dependency failure, retry, and same-byte replay.
3. OCR job enqueue, idempotent replay, failed attempt, retry, and success.
4. Deterministic synthetic OCR, bilingual fact extraction, source mapping, and
   conflict blocking.
5. API fact creation, explicit review, and stale-version rejection.
6. Doctor brief projection from confirmed, source-located facts.
7. Deterministic PDF export bytes for staging evidence.
8. Share access, idempotent share creation, revoke, and post-revoke denial.

The report contains only stage statuses, counts, and stable error categories.
It excludes document text, filenames, opaque IDs, share tokens, credentials,
and source payloads. The PDF step is a synthetic export artifact; the existing
replaceable iOS/API PDF adapter remains the integration seam for a provider
implementation.

For the running Docker composition, use
[`scripts/staging/integration_smoke.py`](../../scripts/staging/integration_smoke.py)
and see [HTTP staging acceptance](integration-acceptance.md). That check goes
through the live API and worker health endpoint, reports whether a worker
actually consumed the queued job, and keeps doctor brief, visit questions, and
PDF route gaps explicitly separate from the deterministic fixture result.
