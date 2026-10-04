# Wayfinder map

## Destination

Deliver an implementation-ready iOS MVP baseline for a source-traceable bilingual visit pack, with frozen product boundaries, API/data contracts, quality gates, privacy controls, and a staged delivery plan.

## Decisions still open

1. First specialty, first delivery channel, and first paying or accepting role.
2. Service entity, data-processing obligations, retention/deletion, and sharing identity verification. Production release is blocked until these are owned and closed; see [ADR-0002 PB-001/PB-006/PB-008](adr/adr-0002-production-boundary-threat-model.md#threat-model-and-executable-controls).
3. OCR/extraction/translation/summary quality contract and human-review path.
4. Minimum iOS version, offline scope, login method, and protected local cache behavior. See [ADR-0002 PB-005](adr/adr-0002-production-boundary-threat-model.md#threat-model-and-executable-controls).
5. Backend state/share contract and operating economics for human review. See [ADR-0002 PB-003/PB-004/PB-006/PB-010](adr/adr-0002-production-boundary-threat-model.md#threat-model-and-executable-controls).
6. Production cloud regions/providers, key rotation and incident ownership, observability redaction, and deletion evidence. See [ADR-0002 PB-002/PB-007/PB-008/PB-009](adr/adr-0002-production-boundary-threat-model.md#threat-model-and-executable-controls).

## Out of scope for the MVP

Diagnosis, treatment or prescription recommendations, image interpretation, automatic EHR write-back, full wearable data, testing marketplaces, and transactional care services.

## Source

The original PRD is maintained outside this repository's code surface. Product facts are copied into the report only as implementation context; the source document remains read-only.
