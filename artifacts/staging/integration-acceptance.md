# HTTP staging acceptance

`integration_smoke.py` exercises the running local API and worker health
boundary with a synthetic document. It does not emit request bodies, tokens,
credentials, opaque IDs, or source text. The report distinguishes HTTP writes
from deterministic fixture projections and lists route gaps instead of calling
missing endpoints.

Run a non-destructive acceptance check after starting Compose:

```sh
python3 scripts/staging/integration_smoke.py --allow-blockers \
  --artifact artifacts/staging/integration-acceptance-report.json
```

The default exit code is `2` when a local blocker is found. Use
`--allow-blockers` only when the report is being collected while the expected
local limitations are present. A generated temporary bearer is used only for
the current local API boundary; set `STAGING_AUTH_TOKEN` to exercise an
approved staging token without printing it. The report keeps this distinction
and never treats the temporary bearer as OAuth/JWT verification.

The live path covers readiness, document and upload-session idempotency,
binary upload replay, processing enqueue and worker completion detection, fact
creation and source spans, stale-version rejection, manual fact review, share
access, expiry, revoke, audit history, and (when requested) provider restart
retention. The current API contract has no HTTP routes for doctor brief, visit
questions, or PDF export; those stages remain explicitly `not_validated` by
the live report and are covered by the existing deterministic fixture smoke.

Provider restart is destructive to in-flight local work and is opt-in:

```sh
python3 scripts/staging/integration_smoke.py --allow-blockers \
  --check-retention --artifact artifacts/staging/integration-acceptance-report.json
```

The retention check restarts PostgreSQL, LocalStack, Redis, API, and Worker
using the ignored `.env.staging`, then verifies readiness and metadata/object
retention. The environment file and service output are never copied into the
report.
