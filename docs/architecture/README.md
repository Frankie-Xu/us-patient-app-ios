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

