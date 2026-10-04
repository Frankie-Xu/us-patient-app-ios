---
title: "ADR-0002: Production boundary threat model and release gates"
status: "Proposed"
date: "2026-10-04"
authors: "Platform, API, iOS and AI architecture"
tags: ["security", "privacy", "threat-model", "production"]
supersedes: ""
superseded_by: ""
---

# ADR-0002: Production boundary threat model and release gates

## Status

**Proposed.** This ADR is the release gate for introducing production services or real patient data. The local in-memory adapters and synthetic fixtures remain valid for development. No production PHI may enter the system until the controls and verification evidence below are accepted by the product owner and the compliance/security owner.

## Context

The MVP crosses five trust boundaries: the iOS device, the authenticated API, durable metadata, encrypted document artifacts, and asynchronous workers. A source-traceable visit pack contains PHI and user-controlled goals/tasks. The API contract describes the domain boundary, but a contract alone does not prove identity mapping, deletion propagation, key custody, recipient controls, or audit completeness.

The threat model is intentionally implementation-oriented. Each row names the asset, the abuse or failure mode, the control that must exist, the evidence that proves it, and the decision still owned by product or compliance. The implementation must fail closed when an evidence item is missing.

## Decision

1. Production adapters must preserve the API contract's ownership, version, idempotency, review and source-reference invariants; infrastructure substitution cannot weaken them.
2. Every production release must attach the verification checklist in [`security-verification.md`](../architecture/security-verification.md) and link evidence for every `PB-*` row below.
3. The service must deny access when identity-to-owner mapping, resource scope, share state, or worker authorization is absent or stale. A client-provided owner id is never an authorization input.
4. PHI stays out of operational logs, metrics, traces, crash reports, queue metadata and CI artifacts. Audit events are a separate append-only stream with scalar, PHI-safe metadata.
5. Deletion, retention, key rotation and share revocation are explicit workflows with observable completion states. A request being accepted is not proof that all replicas or downloaded copies were removed.
6. Open decisions in the Wayfinder map remain release blockers until recorded as accepted decisions with an owner and evidence link.

## Threat model and executable controls

| ID | Asset / trust boundary | Threat or failure mode | Required control | Verification evidence | Unresolved product/compliance decision |
|---|---|---|---|---|---|
| PB-001 | Account identity, bearer session, owner mapping at API gateway → domain service | Token substitution, confused deputy, stale claims, or a client selecting another `owner_id` exposes records | Gateway validates issuer, audience, expiry, nonce/replay policy and key set; maps subject to an internal owner; domain derives owner from `AuthContext`; every repository query enforces owner and resource scope; worker tokens use a separate audience and least-privilege scope | Automated tests for cross-owner reads/writes, expired/revoked token, wrong audience, worker token on user route; signed-token key-rotation drill; authorization decision logs contain IDs only | Identity provider, MFA/recovery, account merge, service-to-service identity, and breach response owner are not selected |
| PB-002 | Original uploads and rendered artifacts in object storage | Public bucket, guessed object key, confused tenant path, stale signed URL, or backup copy leaks PHI | Private buckets; opaque object keys; KMS envelope encryption; service-issued short-lived signed URLs bound to owner/resource/version; no client bucket credentials; malware/media validation; access logs without content | Policy scan shows public access disabled; integration test rejects another owner and expired URL; KMS access review; restore test proves ACLs survive recovery | Cloud region, residency, provider BAA/DPA, malware scanning vendor, and backup retention are open |
| PB-003 | OCR/extraction/translation/render queue | PHI in queue metadata, forged job, replay, unbounded retry, dead-letter leak, or worker overreach | Queue contains opaque job/resource IDs only; payload fetched with worker scope; signed job envelope with expiry and idempotency key; bounded retry and encrypted dead-letter store; worker can write only its job's version | Queue inspection asserts no document text/tokens; forged/replayed/expired job tests fail closed; retry/dead-letter drill; worker scope test | Queue provider, region, maximum retry window, and human access to dead letters need approval |
| PB-004 | PostgreSQL metadata, facts, versions, ownership and idempotency records | Cross-tenant query, injection, stale write, duplicate mutation, or backup exposure | Parameterized queries/ORM; database role separation; row ownership predicates; unique idempotency constraint with request hash; optimistic version checks; encrypted storage and backups; migration review | Schema/permission review; cross-owner and stale-version integration suite; duplicate-key replay test; backup restore with access-control test; migration rollback evidence | RPO/RTO, HA topology, database operator access, backup region and legal hold behavior are open |
| PB-005 | iOS local cache, upload queue, previews and temporary files | Lost device, filesystem backup, screenshots, shared extensions, crash dump, or delete that leaves a copy | Store only minimum metadata by default; Keychain for tokens; file protection (`completeUntilFirstUserAuthentication` or stricter); encrypted app container; no PHI in UserDefaults/analytics; explicit cache purge and upload cancellation; logout/delete clears key material and local files | Device test with locked screen and backup inspection; logout/account-delete test enumerates zero app-owned PHI files; memory/crash/OSLog scan; offline queue cancellation test | Offline scope, minimum iOS version, backup exclusion, accessibility/screenshot policy and “delete from all devices” UX need product/compliance decision |
| PB-006 | ShareVersion, recipient identity and revocation endpoint | Link forwarding, weak recipient verification, token replay, version confusion, or promise that downloaded copies can be revoked | Share is scoped to resource type/id/version and recipient; short expiry; one-time or bounded-use token where required; re-check active/revoked state on every access; audit create/view/revoke; UI states that downloaded copies cannot be recovered | Recipient mismatch/expiry/revoke/version tests; concurrent revoke-versus-fetch race test; audit trail review; client copy review for revocation limitation | Recipient identity proofing, default expiry, one-time versus reusable links, notification channel and institutional sharing policy are open |
| PB-007 | Logs, metrics, traces, crash reports and support exports | PHI, tokens, filenames or full URLs copied into telemetry; high-cardinality identifiers enable re-identification | Central redaction library before emission; allow-list scalar fields; hash or opaque IDs with rotation; query/body/header deny-list; sampling and access controls; support export review | Seeded canary strings through every endpoint/job/client error and assert absent from sinks; static scan of log calls; red-team query; retention/access review | Observability vendor, sampling, support access, cross-border transfer and retention are open |
| PB-008 | Retention/deletion workflow across DB, object store, queue, caches and backups | “Delete” only removes a pointer; orphaned objects, queued jobs, search indexes or backups retain PHI; legal hold conflict | Deletion state machine with idempotent tombstone; stop new access/jobs; fan-out to every store; verifiable completion ledger; queue cancellation and cache purge; backup expiry and legal-hold branch; export before delete only with explicit consent | Deletion drill traces one synthetic subject through every store; orphan scanner; retry/resume and partial-failure alert; legal-hold test; completion report has counts and timestamps | Retention periods by data class, legal hold authority, export format, backup purge guarantee and deletion SLA are open |
| PB-009 | KMS keys, signing keys, database credentials and CI secrets | Key theft, over-broad role, expired signing key, non-atomic rotation or secrets in build logs | KMS/HSM-backed keys; separate encryption/signing/database keys; least-privilege roles; versioned key IDs; dual-key overlap for rotation; automated secret scanning; no long-lived secrets in iOS; emergency revoke/runbook | Quarterly rotation drill with old/new data; signed URL/token validation across overlap; IAM review; secret-scan and build-log inspection; revoke drill | KMS/HSM provider, rotation interval, break-glass approver, escrow and incident SLA are open |
| PB-010 | Append-only AuditEvent stream and security operations | User action omitted, audit record altered, PHI copied into audit, or operators cannot investigate access/deletion | Emit audit events for auth decision, document/version access, fact review, share create/view/revoke, export/delete, key rotation and worker actions; immutable/WORM retention; scalar schema with actor/resource/version/result; clock sync; separate operator access | Event coverage matrix against API routes and jobs; tamper/append-only test; event-to-request correlation drill; clock skew and export review | Audit retention, reviewer access, alert thresholds, SIEM destination and regulatory reporting owner are open |

## Release gates

A production deployment is **blocked** when any of these are missing: owner-scope integration evidence (PB-001/004), private artifact access evidence (PB-002), worker envelope/retry evidence (PB-003), device deletion evidence (PB-005), share revoke race evidence (PB-006), redaction canary evidence (PB-007), deletion completion evidence (PB-008), key rotation evidence (PB-009), or audit coverage evidence (PB-010). A passing unit test without an environment-level evidence link does not satisfy a gate.

The first production data run must use synthetic or explicitly de-identified fixtures, followed by a signed go/no-go record from the product owner and compliance/security owner. Production PHI requires all unresolved decisions above to have an accountable owner, target date and accepted control.

## Consequences

- The local adapters remain replaceable because each production substitution has a named boundary and verification artifact.
- Security work is observable as release evidence rather than an informal checklist.
- Some product choices (offline behavior, recipient identity, retention and support access) remain deliberately blocked until their owners accept the user and regulatory consequences.
- Revocation and deletion communicate enforceable limits; neither claims control over a recipient's downloaded copy or an expired backup that is still under legal hold.

## References

- [`Architecture baseline`](../architecture/README.md)
- [`Security verification runbook`](../architecture/security-verification.md)
- [`ADR-0001 API contract freeze`](adr-0001-api-contract-freeze.md)
- [`Wayfinder map`](../wayfinder-map.md)
