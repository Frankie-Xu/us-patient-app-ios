# API contract

The MVP `/v1` contract is frozen by [ADR-0001](../../docs/adr/adr-0001-api-contract-freeze.md). `openapi.yaml` is the initial HTTP contract for the patient-controlled record organization service. It is intentionally versioned under `/v1` and defines the server-owned entities:

- documents and immutable document versions;
- source-traceable facts with `source_ref`, `source_type`, `confidence`, and `review_status`;
- topics, visits, and tasks;
- upload processing jobs;
- expiring, version-pinned share versions with revoke semantics; and
- PHI-safe audit events.

Mutating requests require `Idempotency-Key`. Review writes use `If-Match-Version` and return a conflict when a newer immutable version exists. A revoked or expired share blocks new access; the contract does not claim that downloaded copies can be recovered.

Authentication is a gateway concern. The gateway validates bearer tokens and supplies scopes; the service enforces scope and ownership boundaries. Audit metadata is scalar operational data only. Document text, claims, filenames, tokens, credentials, and real patient records are excluded from logs and fixtures.

The service skeleton in `services/api` uses an in-memory adapter for local tests. A durable database, object store, job runner, identity provider, and PHI retention/deletion policy remain open deployment decisions.
