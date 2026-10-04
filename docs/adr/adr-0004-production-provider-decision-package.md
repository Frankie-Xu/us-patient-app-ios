---
title: "ADR-0004: production provider and deployment decision package"
status: "Proposed — awaiting Product and Compliance/Security approval"
date: "2026-10-05"
authors: "Product, Compliance/Security, Engineering and Incident owners"
tags: ["production", "providers", "privacy", "deployment", "decision-package"]
supersedes: ""
superseded_by: ""
---

# ADR-0004: Production provider and deployment decision package

## Purpose and decision boundary

This package turns Issue #37 and the Wayfinder dependencies into a reviewable
decision register. It does not select a vendor, region, identity service,
database, object store or queue. Candidate entries are capability classes so the
team can compare approved options without coupling the domain code to a
provider.

The package is an implementation gate. Synthetic and appropriately de-identified
testing may continue. Production PHI remains No-Go until the Product Owner and
Compliance/Security Owner approve the applicable rows, attach evidence and name
an operational owner.

## Existing baseline that this package must preserve

- Wayfinder ticket 01 fixes the initial specialty, channel and MVP slice.
- Wayfinder ticket 02 owns the service entity, data processing, retention/deletion
  and sharing controls.
- Wayfinder ticket 04 owns the iOS minimum, offline scope, login and protected
  cache.
- Wayfinder ticket 05 owns the backend/share contract and audit semantics.
- ADR-0002 requires fail-closed identity, private artifacts, scoped workers,
  redacted telemetry, verifiable deletion, key rotation and scalar audit.
- ADR-0003 proposes US adult primary care, a US-region-first posture, online-first
  iOS state, 30-day default retention, 24-hour scoped shares, 7-day telemetry
  retention, 90-day audit retention and 90-day key-rotation targets.

## Decision register

The recommendation column is a default for review. It becomes an accepted
decision only when the named owner records approval and evidence.

| Area | Candidate options | Recommended default for review | Decision owner and evidence | Blocking impact |
|---|---|---|---|---|
| Service entity and data processing | US operating entity; non-US entity with US processing; hybrid entity/subprocessor model | Use the entity that can sign the required business-associate/data-processing agreements and own incident response; keep processing in approved US regions until exceptions are accepted | Product + Compliance/Security: entity record, data-flow map, BAA/DPA inventory and signed agreements | No production PHI, support access or provider onboarding |
| Identity and session boundary | Managed OIDC/OAuth2 service; enterprise identity federation; self-hosted OIDC service | Managed OIDC/OAuth2 with issuer, audience, MFA, recovery, key rotation and revocation evidence; domain code receives verified AuthContext only | Compliance/Security + Engineering: issuer/audience record, MFA/recovery runbook, key-rotation drill and owner mapping tests | No production login, reviewer links or account recovery |
| Data residency and support access | Single US region; US primary plus approved US disaster-recovery region; cross-border active/active | US primary plus an explicitly approved US disaster-recovery region; prohibit cross-border support and replica access by default | Compliance/Security: residency map, subprocessors, support-access matrix and restore evidence | No storage, backup, analytics or incident export approval |
| Relational metadata and migrations | Managed PostgreSQL; self-hosted PostgreSQL; relational serverless database | Managed PostgreSQL capability with private networking, encryption, point-in-time recovery, row ownership predicates and reviewed forward/rollback migrations | Engineering + Compliance/Security: schema review, role review, restore test, migration rehearsal and RPO/RTO | No durable metadata or audit production adapter |
| Original and rendered artifacts | Private managed object storage; database BLOBs; encrypted filesystem | Private managed object storage with opaque keys, envelope encryption, short-lived service-issued access and lifecycle policies | Engineering + Compliance/Security: public-access policy scan, KMS review, access test, restore/ACL evidence and retention configuration | No upload, preview, share or deletion production adapter |
| Processing queue and worker | Managed durable queue; database outbox plus worker; self-hosted broker | Managed durable queue or reviewed outbox with opaque IDs only, signed worker envelope, bounded retry, encrypted dead-letter handling and least-privilege worker identity | Engineering + Incident: queue metadata scan, replay/expiry tests, retry/dead-letter drill and operator access record | No OCR/extraction/render worker or async PHI flow |
| BAA/DPA and subprocessor control | Direct agreement with every processor; platform agreement plus listed subprocessors; no-PHI pilot until agreement | Maintain a processor inventory and execute the required agreements before enabling PHI; attach data-flow and deletion commitments for each subprocessor | Compliance/Security: signed agreement set, subprocessors, transfer assessment and renewal owner | Production PHI and external support are prohibited |
| Retention, legal hold and deletion | Fixed retention; class-specific retention; indefinite retention | Use ADR-0003 defaults initially: 30-day default, legal hold override, idempotent deletion fan-out to metadata, object store, queue, protected cache and eligible backups | Product + Compliance/Security: retention schedule, legal-hold authority, deletion SLA, completion report and orphan scan | No production deletion or user-facing retention promise |
| Share recipient verification | Verified reviewer identity; email one-time code; open bearer link | Verified reviewer identity with resource/version/recipient scope, 24-hour default expiry, revoke re-check and copy limitation language | Product + Compliance/Security: recipient proofing, notification channel, revoke-race evidence and approved UX copy | No clinician delivery or share release |
| Incident response and operations | Named internal on-call; managed response service; shared responsibility | Name an Incident Owner, severity matrix, escalation SLA, break-glass approver and rollback path; exercise with synthetic data before PHI | Incident + Compliance/Security: runbook, contact coverage, tabletop/restore drill and evidence links | No production launch or PHI incident handling |

## Provider-neutral contract already implemented

The following seams are merged and intentionally provider-neutral:

- MetadataStore, ObjectStore and JobQueue protocols with local/staging durable
  SQLite adapters, readiness checks, idempotency and optimistic versioning.
- SQLite schema version guardrails that promote legacy version zero and reject
  unsupported future versions.
- Environment validation requiring HTTPS and reference-only secrets outside local
  development; direct credential-bearing keys are rejected.
- In-memory retention and deletion contract seams that model legal holds,
  idempotent requests, retryable target failures and completion across all
  required targets.

The staging lifecycle adapter records a synthetic completion ledger only. It does
not delete bytes, call a provider, or authorize production PHI.

## Decisions that must wait for approval

Do not implement provider SDKs, production credentials, real identity verification,
cross-region replicas, production backup deletion, external malware scanning,
production observability export, or PHI-enabled staging until the relevant register
row has an owner, an accepted option, evidence requirements and a signed
Go/Pause/No-Go disposition.

The following engineering work can proceed without those decisions:

- contract tests against the protocols and synthetic fixtures;
- adapter factories that accept interfaces and secret references;
- migration rehearsal tooling with local fixtures;
- deletion ledger and readiness behavior;
- iOS online-first flows, protected-cache purge and share/revoke UX using synthetic
  data.

## Approval record

Before provider-specific work starts, record for every accepted row:

1. Decision ID and selected capability option.
2. Product, Compliance/Security, Engineering or Incident owner.
3. Data classes and regions affected.
4. Required evidence link and target date.
5. Go, Pause or No-Go disposition.
6. Review date, rollback owner and superseding ADR if the decision changes.

Until this record is complete, Issue #37 remains open and production PHI is blocked.

## References

- Issue #37: production provider and deployment contract
- Issue #41: retention and deletion lifecycle seams
- Wayfinder map: docs/wayfinder-map.md
- ADR-0002: production boundary threat model
- ADR-0003: US primary-care pilot operating baseline
- services/api/lifecycle.py
