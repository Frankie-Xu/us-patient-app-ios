# Architecture baseline

## Boundary

The iOS client owns task-oriented presentation, local upload state, document preview, fact review, visit-pack editing, and sharing controls. Services own authentication, object storage, immutable document versions, OCR/extraction jobs, source references, audit events, PDF rendering, and revocation enforcement.

## Dependency rule

`View → Feature ViewModel → Domain UseCase → Repository → API/Cache`.

Views do not build URLs, parse vendor payloads, or infer clinical meaning. Domain types do not import SwiftUI. Repositories return typed domain results and surface review/permission states explicitly.

## Core entities

`Document`, `Fact`, `Topic`, `Visit`, `Task`, `ShareVersion`, and `AuditEvent` are server-owned. A write creates a new version or a state event; clients do not silently overwrite prior facts.

## Non-negotiable invariants

- A fact without `source_ref` or explicit `user_input` cannot enter the default doctor view.
- A conflict is displayed side by side until a patient or authorized reviewer resolves it.
- A revoked share blocks new access but does not claim to recover downloaded copies.
- AI output cannot be promoted to confirmed without an explicit review action.
- Production adapters must fail closed on missing owner scope, stale versions, expired/revoked shares and incomplete deletion.
- Production PHI is blocked until the evidence gates in [ADR-0002](../adr/adr-0002-production-boundary-threat-model.md) pass.

## Production boundary

The API/auth gateway maps external identity to an internal owner and passes an explicit `AuthContext` to domain services. PostgreSQL owns relational metadata, ownership, versions, idempotency and audit references. Encrypted object storage owns originals and rendered artifacts. A durable queue carries opaque job IDs and signed worker envelopes. iOS keeps the minimum protected cache and supports explicit logout/account-delete purge. Operational telemetry is PHI-redacted; audit events are scalar and append-only.

The executable threat model and evidence matrix are in [ADR-0002](../adr/adr-0002-production-boundary-threat-model.md), with the release runbook in [security-verification.md](security-verification.md).
