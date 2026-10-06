# API service skeleton

The core in `models.py`, `store.py`, and `service.py` is typed with Python stdlib dataclasses and an explicit in-memory adapter. It provides the use-case boundary for documents, source-traceable facts, topics, visits, tasks, upload jobs, shares, idempotency, immutable version checks, and audit events.

`contract_fixtures.py` is the dependency-free client-generation seam. It
provides typed synthetic request fixtures for visit-pack and sharing writes,
validates account-history and sharing responses against the frozen OpenAPI
field and value sets, and fails closed on unknown fields, malformed values,
invalid nullability, missing required fields, nested shape drift, or contract
drift. `serialize_payload`/`canonical_json` provide a sorted-key, compact JSON
representation with non-finite and opaque values rejected. Validation and
serialization errors never echo payload values, tokens, or filesystem paths.
It is intentionally provider-neutral and does not parse credentials or carry
real patient data.

`app.py` is an optional FastAPI adapter. Install the dependencies declared in `pyproject.toml` to run HTTP routes; authentication remains a gateway concern and is represented in the core by `AuthContext` and scopes. Replace `InMemoryStore` with a transactional database/object-storage adapter before handling production PHI.

Run the dependency-free tests from the repository root:

```sh
python3 -m unittest discover -s services/api/tests -p 'test_*.py'
```

The CI test path uses `requirements-ci.txt`, a hash-pinned export of the API
runtime and test graph. Refresh it intentionally when `pyproject.toml` changes;
Dependabot monitors the file together with the project metadata.

## HTTP adapter

`app.py` exposes `create_app()` when the optional FastAPI dependencies are installed. The framework-neutral `ApiHttpAdapter` is the local integration seam used by tests. Its temporary bearer header format is `Bearer <subject>|<comma-separated scopes>|<comma-separated roles>`; this only adapts test headers to `AuthContext` and does not validate production credentials.

`ApiService` accepts `ObjectStore` and `JobQueue` protocols through dependency injection. `InMemoryObjectStore` and `InMemoryJobQueue` are local doubles only; no network, credentials, or real patient payloads are used. `/healthz` reports process liveness, while `/readyz` reports metadata, object-store, and queue availability and returns `503` when any dependency is unavailable.


HTTP errors use the stable envelope `{ "code": "...", "detail": "..." }`. Current codes are `AUTHENTICATION_REQUIRED`, `FORBIDDEN`, `NOT_FOUND`, `SHARE_NOT_FOUND`, `IDEMPOTENCY_CONFLICT`, `VERSION_CONFLICT`, `VALIDATION_ERROR`, `SERVICE_ERROR`, `SHARE_EXPIRED`, `SHARE_REVOKED`, `DEPENDENCY_UNAVAILABLE`, `UPLOAD_TOO_LARGE`, `UPLOAD_INTEGRITY_MISMATCH`, `UPLOAD_EXPIRED`, `UPLOAD_SESSION_CONFLICT`, and `INTERNAL_ERROR`. Details are kept operational and never echo request bodies, filenames, claims, or tokens.

The HTTP adapter also exposes the frozen visit-preparation writes: `POST /v1/topics`, `POST /v1/visits`, and `POST /v1/tasks`. Visit and task timestamps require timezone-aware ISO-8601 values; `topic_ids` is an array and `visit_id` is nullable.

## Bounded binary upload sessions

Phase 8 adds `POST /v1/documents/{documentId}/upload-sessions` (`{}` plus `Idempotency-Key`) and `PUT /v1/upload-sessions/{uploadSessionId}/content` (raw bytes, `Content-Type: application/octet-stream`). A session binds the current uploaded document version, expected size and normalized SHA-256 for 15 minutes. Uploads are limited to 1–10 MiB. Bytes are checked before an injected `ObjectStore.put`; storage failure leaves a pending session that can be retried. The FastAPI adapter consumes the request stream with the same size cap.

The verified receipt is safe to replay with identical bytes; it does not expose the provider key or write a second audit event. Changed bytes return `UPLOAD_INTEGRITY_MISMATCH` (422), expired pending sessions `UPLOAD_EXPIRED` (410), changed documents `UPLOAD_SESSION_CONFLICT` (409), oversized uploads `UPLOAD_TOO_LARGE` (413), and unavailable adapters `DEPENDENCY_UNAVAILABLE` (503). Existing document metadata creation and processing semantics remain compatible. Verification does not start OCR or mark a document ready.

Use synthetic bytes only. Production requires authenticated gateway limits, streaming encrypted durable storage, malware/content checks, transactional metadata receipt handling, abandoned-object cleanup and retention/deletion decisions. No cloud service is configured by this skeleton.


## Account-history reads

`GET /v1/topics` and `GET /v1/visits` require `visits:read`; `GET /v1/tasks` requires `tasks:read`. They reuse the existing owner/reviewer/service visibility rule, return `200` with an empty array for an empty account, and sort by server creation time ascending with an ID tie-breaker. The adapter never accepts a client sort expression or exposes records from another owner without reviewer/service authorization.

## Provider-neutral metadata boundary (Phase 10A)

`ApiService` depends on the `MetadataStore` protocol rather than `InMemoryStore` internals. The protocol is limited to readiness, resource reads/lists, version-aware saves, actor-scoped idempotency receipts, and PHI-safe audit append/read operations. `InMemoryStore` remains the dependency-free test implementation and keeps its public collections for fixture assertions.

Omitted constructor dependencies use the local in-memory doubles for offline tests. An explicitly missing dependency (`None`), a provider reporting unavailable, or a provider raising during `is_ready()` makes `/readyz` return `503` with `DEPENDENCY_UNAVAILABLE`; the service never claims readiness on an incomplete startup graph. No database, cloud provider, queue, credential, or PHI adapter is included.


## Gateway claims boundary (Phase 11A)

The gateway may pass a verified `GatewayClaims` mapping to `auth_context_from_gateway_claims`. The core accepts issuer, audience, subject, expiry, request ID, roles and scopes only after typed validation. Issuer and audience must match deployment configuration; expiry and provider-neutral revoked/disabled/inactive states fail closed; roles and scopes must map to the explicit `PrincipalRole` and `Scope` allowlists. Empty subjects/request IDs, malformed timestamps, unknown values and missing claims are rejected.

The core does not parse JWTs, verify signatures, call an identity provider, or log token material. The existing temporary `Bearer subject|scopes|roles` adapter remains a local test seam and is intentionally separate from the gateway claim mapper.


## Durable development adapters

Phase 14 adds restart-safe SQLite adapters behind the existing MetadataStore, ObjectStore, and JobQueue protocols. They are intended for local development and staging contract tests: the app still fails closed when an adapter is unavailable, and queued payloads remain metadata-only.

The SQLite adapters do not claim production PHI compliance. A production deployment must replace them with encrypted managed storage, reviewed migrations, backup/restore controls, access logging, and a durable worker with an explicit data-processing agreement. Keep database paths outside the repository and never use real patient data in local fixtures.


## Schema version and migration boundary (Phase 16)

The local SQLite metadata, object, and queue adapters record schema version 1
via SQLite PRAGMA user_version. Existing Phase 14 databases start at version
zero, are initialized in place, and are promoted to version one. An adapter
that sees a newer or unsupported version fails closed instead of silently
changing the database. Production adapters must use an encrypted managed
database/object store/queue with reviewed forward migrations, rollback plans,
backup compatibility checks, and an operator evidence link.


## Retention and deletion lifecycle boundary (Phase 17)

The provider-neutral RetentionPolicy and DeletionCoordinator protocols make
retention deadlines, legal holds, idempotent requests and cross-store completion
explicit. The in-memory staging implementation covers metadata, object storage,
job queue, protected cache and eligible backup targets. It records state only and
never deletes bytes. Production adapters must replace it with a durable,
auditable workflow that stops new work, fans out deletion, preserves legal holds,
supports retry/resume and reports completion across every approved store.


## Staging runtime composition (Phase 18)

RuntimeDependencies is the provider-neutral dependency graph for local/staging:
metadata store, object store, queue, retention policy and deletion coordinator.
Its aggregate readiness is fail-closed and exposes one check per boundary. The
build_local_runtime factory writes SQLite files only under the caller-provided
local directory and wires the synthetic lifecycle adapters. It is intended for
contract tests and staging rehearsals; production startup must inject approved
provider implementations after Issue #37 decisions are accepted.
