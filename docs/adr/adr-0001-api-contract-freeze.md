---
title: "ADR-0001: Freeze the MVP API contract and persistence boundaries"
status: "Accepted"
date: "2026-10-04"
authors: "API and iOS architecture"
tags: ["architecture", "api", "privacy", "persistence"]
supersedes: ""
superseded_by: ""
---

# ADR-0001: Freeze the MVP API contract and persistence boundaries

## Status

**Accepted**

The `/v1` contract is frozen for the MVP implementation baseline. This records the interfaces and safe defaults that can be consumed by the iOS client while production infrastructure decisions remain explicitly open.

## Context

The MVP loop is `upload → processing → review → share`. The server owns document metadata, immutable versions, source-traceable facts, visit preparation entities, upload jobs, share versions, and audit events. The client must be able to render source coverage, confidence, review state, optimistic version conflicts, and share expiry/revocation limits without inferring clinical meaning.

The repository does not yet have a production database, object store, queue, identity provider, retention policy, or historical-version store. The contract therefore needs a stable boundary that is safe to test locally and clear about what is not yet promised.

## Decision

- **DEC-001**: Freeze `packages/contracts/openapi.yaml` as the `/v1` MVP contract for Document, Fact, Topic, Visit, Task, ShareVersion, AuditEvent, and UploadProcessingJob.
- **DEC-002**: Require `Idempotency-Key` on mutating requests and use `If-Match-Version` for review writes. Reusing an idempotency key with a different request body is a conflict; stale versions are a conflict.
- **DEC-003**: Require every Fact to carry `source_ref`, `source_type`, `confidence`, and `review_status`. AI-created facts remain unreviewed until an explicit patient or authorized reviewer action.
- **DEC-004**: Treat authentication as a gateway boundary. The gateway validates bearer credentials and maps claims to service scopes; the domain service enforces scopes, ownership, and service-only worker actions through `AuthContext`.
- **DEC-005**: Record audit events separately from operational telemetry. Audit metadata is scalar and PHI-safe; document text, claims, bearer tokens, filenames, and clinical payloads are excluded.
- **DEC-006**: Use an in-memory adapter and synthetic fixtures for the local skeleton. The production default is PostgreSQL for relational metadata, encrypted object storage for originals/rendered artifacts, and a durable queue for OCR/extraction/translation/render jobs.
- **DEC-007**: A ShareVersion pins a resource type, resource id, and resource version, has an expiry, and can be revoked. Revocation blocks new access before expiry and never claims to recover downloaded copies.

## Consequences

### Positive

- **POS-001**: iOS can generate a typed client against a stable, source-traceable contract.
- **POS-002**: Retry-safe writes and optimistic conflicts prevent duplicate uploads and silent overwrites.
- **POS-003**: Explicit auth, audit, and PHI boundaries make local tests safe and production adapters replaceable.
- **POS-004**: Share behavior communicates the practical limit of revocation instead of implying control over downloaded copies.

### Negative

- **NEG-001**: The current service adapter does not provide durable persistence, disaster recovery, or cross-process job delivery.
- **NEG-002**: Historical versions are represented by version metadata, but the local adapter cannot yet retrieve an older materialized snapshot.
- **NEG-003**: The token vault used for local idempotent share replay is process-local; a production implementation must use a protected, non-plaintext token strategy.
- **NEG-004**: Retention, deletion, legal hold, identity verification, and reviewer staffing are not settled by this contract.

## Alternatives Considered

### Adopt a FHIR/EHR-first contract

- **ALT-001**: **Description**: Make FHIR resources and institution connectors the primary API surface for the first release.
- **ALT-002**: **Rejection Reason**: The MVP source is patient-controlled uploads and review; institution support, data-processing obligations, and source coverage are not yet verified.

### Use a document database as the default store

- **ALT-003**: **Description**: Store documents, facts, shares, and audit events as nested records in a document database.
- **ALT-004**: **Rejection Reason**: Relational ownership, version checks, idempotency uniqueness, audit queries, and expiry/revoke state are clearer and more enforceable with PostgreSQL.

### Let the iOS client own fact versions

- **ALT-005**: **Description**: Treat the client as the source of truth and submit complete replacements from the device.
- **ALT-006**: **Rejection Reason**: This permits silent overwrites, weakens auditability, and cannot reliably enforce review state or source coverage across devices.

### Make share revocation retroactive

- **ALT-007**: **Description**: Promise that revoking a share invalidates or retrieves copies already downloaded by recipients.
- **ALT-008**: **Rejection Reason**: The service cannot control recipient storage after delivery; the contract states the enforceable boundary instead.

## Implementation Notes

- **IMP-001**: PostgreSQL is the current production default for relational metadata, ownership, idempotency records, version metadata, share state, and append-only audit records.
- **IMP-002**: Originals and rendered artifacts belong in encrypted object storage with KMS-managed keys, access logging, retention hooks, and no direct client bucket credentials.
- **IMP-003**: OCR, extraction, translation, and render jobs should run through a durable queue with retry/dead-letter behavior; job payloads must follow the PHI redaction policy.
- **IMP-004**: Before production PHI, decide retention periods, deletion propagation across database/object store/queue/backups, legal holds, and identity verification for recipients.
- **IMP-005**: Before sharing an older version, add durable historical snapshots and make `resource_version` resolve to that exact snapshot rather than the latest mutable projection.

## References

- **REF-001**: `packages/contracts/openapi.yaml`
- **REF-002**: `docs/architecture/README.md`
- **REF-003**: `docs/technology-route.md`
- **REF-004**: `docs/wayfinder-map.md`
