# API contract

The MVP `/v1` contract is frozen by [ADR-0001](../../docs/adr/adr-0001-api-contract-freeze.md). `openapi.yaml` is the initial HTTP contract for the patient-controlled record organization service. It is intentionally versioned under `/v1` and defines the server-owned entities:

- documents and immutable document versions;
- source-traceable facts with `source_ref`, `source_type`, `confidence`, and `review_status`;
- topics, visits, and tasks;
- upload processing jobs and bounded upload sessions;
- expiring, version-pinned share versions with revoke semantics; and
- PHI-safe audit events.

POST creation requests require `Idempotency-Key`. The additive binary PUT is naturally idempotent because its session pins size and checksum. Review writes use `If-Match-Version` and return a conflict when a newer immutable version exists. A revoked or expired share blocks new access; the contract does not claim that downloaded copies can be recovered.

Authentication is a gateway concern. The gateway validates bearer tokens and supplies scopes; the service enforces scope and ownership boundaries. Audit metadata is scalar operational data only. Document text, claims, filenames, tokens, credentials, and real patient records are excluded from logs and fixtures.

The service skeleton in `services/api` uses an in-memory adapter for local tests. A durable database, object store, job runner, identity provider, and PHI retention/deletion policy remain open deployment decisions.

## Typed fixture compatibility (Phase 12)

`services/api/contract_fixtures.py` contains dependency-free typed synthetic
request fixtures for the visit pack (`TopicCreate`, `VisitCreate`, and
`TaskCreate`) and sharing (`ShareCreate`). Response validators cover the
corresponding account-history resources plus `ShareReceipt` and
`SharedResource`. The fixture module snapshots the required and property field
sets from this frozen OpenAPI file. Unknown fields, missing required fields, or
schema drift fail closed in the API test suite, keeping a future generated
client from silently accepting an incompatible payload. Fixtures contain no
credentials or clinical records.

## Additive upload-session boundary (Phase 8)

The frozen document metadata routes remain compatible. After registering metadata, create a session with `POST /v1/documents/{documentId}/upload-sessions` and `{}`. Send raw bytes to `PUT /v1/upload-sessions/{uploadSessionId}/content` with `Content-Type: application/octet-stream`. Each pending session lasts 15 minutes and supports 1–10 MiB inclusive. The server checks exact size and SHA-256 before writing; successful identical PUT retries return the original verified receipt.

Session ownership requires `documents:write`; stale document versions, expired pending sessions, oversized bodies, mismatched bytes and unavailable storage use stable error codes. Provider keys and binary content stay out of responses, idempotency records and audit. Verification leaves document metadata unchanged and does not auto-enqueue processing. This in-memory adapter has no cloud credentials, malware scanning, durable staging, resumable transfer, retention/deletion or production PHI support.

## Account-history reads (Phase 9A)

`GET /v1/topics` and `GET /v1/visits` require `visits:read`; `GET /v1/tasks` requires `tasks:read`. Each returns an array scoped to the authenticated owner. Reviewer and service roles may read across owners when the gateway grants the corresponding read scope. Results use ascending server `created_at` order with the opaque record ID as a deterministic tie-breaker. Empty accounts return `200` with `[]`; no pagination or client-provided ordering is accepted in this phase.
