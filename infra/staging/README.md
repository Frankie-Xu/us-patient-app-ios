# Staging runtime composition

This composition provides a provider-neutral staging graph with PostgreSQL,
MinIO, a migration gate, a database-queue startup gate, deterministic API/AI
worker placeholders, and a background task worker. It contains no real
provider credentials, production DNS, or patient data.

## Startup contract

1. postgres and minio become healthy.
2. migration replays the idempotent SQL baseline and records
   schema_migrations(version=1).
3. queue-init verifies that processing_jobs exists and the migration marker
   is present.
4. object-storage-init creates the configured private S3-compatible bucket.
5. api, ai-worker, and task-worker start only after both gates complete.

The long-lived placeholders expose /healthz and /readyz. The API placeholder
also exposes a bounded /handoff endpoint that acknowledges a synthetic upload
without logging or persisting its body. These processes are intentionally
provider-neutral and are not production API or worker implementations.

## Local rehearsal

1. Copy .env.example to .env; keep all values local.
2. Render and validate the service graph:

       bash scripts/staging/run-smoke.sh

3. For a live local rehearsal, run the graph with
   docker compose --env-file .env -f infra/staging/docker-compose.yml up -d.
4. Confirm all three long-lived services report healthy:

       curl -fsS http://127.0.0.1:${STAGING_API_PORT:-8080}/healthz

5. Use only synthetic documents and remove named volumes after the rehearsal.

run-smoke.sh also invokes the existing scripts/staging_e2e.py when that file
is present in the checkout. It deliberately does not duplicate or replace the
end-to-end workflow.

## Acceptance entrypoint

Use the composed acceptance entrypoint after the existing full workflow harness
is present:

       bash scripts/staging/run-acceptance.sh

It verifies the runtime composition contract, invokes the existing retry and
idempotency harness, and invokes scripts/staging_e2e.py for the upload through
revoke flow. It emits a redacted JSON summary, identifies the failing stage,
and returns a non-zero status on a failed or blocked stage. The entrypoint only
orchestrates existing harnesses; it does not reimplement API or AI business
logic and never logs document bytes or patient data.

A checkout that intentionally omits scripts/staging_e2e.py can rehearse the
runtime and resilience stages with:

       STAGING_ACCEPTANCE_ALLOW_MISSING_FULL_FLOW=1 bash scripts/staging/run-acceptance.sh

That mode marks the patient flow as deferred so it cannot be mistaken for a
complete acceptance.
