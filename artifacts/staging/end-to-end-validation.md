# Local staging end-to-end validation

Date: 2026-10-06 (Asia/Singapore)

The live report in `integration-acceptance-report.json` completed with
`status=passed` and zero blockers using synthetic data. The Worker used the
configured `qwen-vl-ocr` provider for the PNG fixture; it did not use fixture
text ingest or real patient data.

| Stage | Verification | Result |
| --- | --- | --- |
| Readiness | live HTTP | passed |
| Upload and checksum/idempotency | live HTTP | passed |
| S3 content replay | live HTTP | passed |
| Queue processing and OCR | live HTTP + provider Worker | passed |
| Text normalization and bilingual fixture extraction | deterministic AI adapter | passed |
| Source mapping and conflict gate | live HTTP + deterministic fixture | passed |
| Manual fact review and version conflict | live HTTP | passed |
| Doctor brief | deterministic fixture projection | passed in mock boundary |
| Visit questions | deterministic fixture projection | passed in mock boundary |
| PDF export | deterministic fixture projection | passed in mock boundary |
| Share access | live HTTP | passed |
| Expiry and revoke denial | live HTTP | passed |
| PostgreSQL/S3 retention after restart | live HTTP | passed |

Failure coverage includes duplicate document/job submission, stale fact
versions, provider retryable errors, terminal provider errors, short-TTL
expiry, and post-revoke access denial. Reports contain statuses and error
categories only; they contain no source text, tokens, credentials, or PHI.

The current HTTP contract has no routes for doctor brief, visit questions, or
PDF export, so those three stages remain explicitly fixture-backed until the
contract is extended. External OAuth/JWT issuer configuration is also not part
of local staging validation.
