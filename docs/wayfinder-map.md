# Wayfinder map

## Destination

Deliver an implementation-ready iOS MVP baseline for a source-traceable bilingual visit pack, with frozen product boundaries, API/data contracts, quality gates, privacy controls, and a staged delivery plan.

## Build baseline frozen; production gate pending sign-off

The six decisions below are frozen as the proposed build baseline for implementation and synthetic/de-identified testing. They are not legal/compliance approval. Production PHI remains **No-Go** until the named owners sign the evidence in [ADR-0003](adr/adr-0003-pilot-operating-baseline.md) and the threat-model gates in [ADR-0002](adr/adr-0002-production-boundary-threat-model.md).

1. **Pilot and roles:** US adult primary care/family medicine; iOS patient channel; short-lived revocable clinician-reviewer link; patient and authorized clinical reviewer roles. See [ADR-0003 D1](adr/adr-0003-pilot-operating-baseline.md#d1--pilot-and-roles).
2. **US entity and compliance gate:** US entity, US-region-first operation, and service entity/BAA/DPA/compliance owner sign-off before PHI. See [ADR-0003 D2](adr/adr-0003-pilot-operating-baseline.md#d2--us-entity-region-and-compliance-gate).
3. **Identity boundary:** Provider-neutral OIDC/OAuth2 gateway, MFA/recovery, internal owner mapping and reviewer scope; provider selection awaits compliance approval. See [ADR-0003 D3](adr/adr-0003-pilot-operating-baseline.md#d3--provider-neutral-identity-boundary).
4. **Online-first local state:** Minimum in-memory/protected-container cache; logout/account-switch purge; full offline records are No-Go. See [ADR-0003 D4](adr/adr-0003-pilot-operating-baseline.md#d4--online-first-and-minimal-local-state).
5. **Retention/deletion:** 30-day default retention, user deletion request, legal-hold override and verifiable DB/object/queue/cache deletion. See [ADR-0003 D5](adr/adr-0003-pilot-operating-baseline.md#d5--retention-and-deletion).
6. **Sharing, telemetry and keys:** 24-hour resource/version/recipient-scoped shares with revoke re-check; downloaded copies cannot be recalled; scalar-only telemetry retained 7 days, audit 90 days (or legal hold), 90-day key-rotation target. See [ADR-0003 D6/D7](adr/adr-0003-pilot-operating-baseline.md#d6--controlled-sharing).

## Accountability

Product Owner, Compliance/Security Owner, Engineering Owner and Incident Owner are fixed decision roles. The implementation may proceed on synthetic/de-identified data while evidence is gathered; a passing build or CI run does not substitute for legal/compliance sign-off.

## Out of scope for the MVP

Diagnosis, treatment or prescription recommendations, image interpretation, automatic EHR write-back, full wearable data, testing marketplaces, and transactional care services.

## Source

The original PRD is maintained outside this repository's code surface. Product facts are copied into the report only as implementation context; the source document remains read-only.
