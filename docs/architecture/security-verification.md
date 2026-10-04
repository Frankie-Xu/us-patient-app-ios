# Production boundary security verification

This runbook turns [ADR-0002](../adr/adr-0002-production-boundary-threat-model.md) into evidence that can be attached to a release. It uses synthetic/de-identified records only. Never paste tokens, document text, filenames, signed URLs or patient identifiers into the evidence bundle.

## Before each production-data decision

1. Record the commit, environment, test dataset classification and verifier.
2. Run the repository validation and contract tests from the repository root. Attach their exit status and CI URL.
3. Run the environment checks below against a disposable tenant and a synthetic subject. Record pass/fail, timestamps and redacted request IDs.
4. Link each result to its `PB-*` row. A missing result is a blocked gate; a prose assertion is not evidence.
5. Obtain separate product and compliance/security sign-off for every open decision in the ADR and Wayfinder map.

## Environment checks

| Check | Procedure | Pass condition | Evidence |
|---|---|---|---|
| Identity and ownership (`PB-001`) | Create two tenants; replay expired, wrong-audience, wrong-owner and worker credentials against read/write routes | Every unauthorized call is denied; no response reveals whether the other tenant's resource exists | Redacted status codes, policy version and test run ID |
| Artifact isolation (`PB-002`) | Request object URLs as owner, another owner and after expiry/revoke; inspect bucket policy | Only active owner-scoped URL works; bucket is private; no direct credential appears in app/config | Policy export, URL test results and KMS key ID (never key material) |
| Queue boundary (`PB-003`) | Submit forged, replayed, expired and duplicate job envelopes; force retry/dead-letter | Invalid jobs are rejected; retries are bounded; dead-letter metadata has opaque IDs only | Queue policy, envelope test output and redacted DLQ sample |
| Database boundary (`PB-004`) | Run cross-owner, stale-version and idempotency-reuse integration tests; restore a backup to a quarantine instance | Ownership predicate and version conflict are enforced; same key/body is idempotent; different body conflicts | Migration/version, test run ID and restore ACL result |
| Device cache/delete (`PB-005`) | Lock device, inspect backups/logs, enqueue offline upload, logout, then account-delete | No token/PHI in logs or unprotected storage; queue stops; app-owned files and keys are removed | Device/OS version, file inventory counts, redacted log scan |
| Share lifecycle (`PB-006`) | Create recipient-scoped share; race fetch with revoke; test expiry and version pin | Unauthorized/expired/revoked fetch fails; downloaded-copy limitation appears in UI and support text | State transition trace and UI copy review |
| Telemetry redaction (`PB-007`) | Send seeded canary values in headers, body, filenames and errors through API, worker and iOS flows | Canary values are absent from logs, metrics, traces, crash and support exports | Sink scan query, redacted result and retention setting |
| Deletion (`PB-008`) | Delete a synthetic subject during processing and during legal hold; retry a partial failure | New access/jobs stop; all non-held stores reach completed state; failures alert and resume idempotently | Deletion ledger, orphan scan, hold decision and completion timestamp |
| Key rotation (`PB-009`) | Rotate signing/encryption/database keys with overlap; revoke the old key | New writes use the new key; reads during overlap work; old key cannot mint or decrypt after revoke | Key version IDs, IAM review and rotation drill record |
| Audit (`PB-010`) | Exercise auth, access, review, share, export, delete, worker and rotation actions; attempt event mutation | Each action has scalar actor/resource/version/result metadata; stream is append-only and queryable | Coverage matrix, tamper test and correlation IDs |

## Evidence handling

Store only redacted test metadata in the release record: commit, environment, test ID, status, timestamps, counts and control/version IDs. Keep raw device logs, infrastructure exports and failure samples in the approved restricted evidence store with its own retention and access policy. Do not attach raw logs to pull requests.

## Exit criteria

The verifier may recommend **Go** only when all ten `PB-*` controls have passing evidence and all product/compliance decisions have an owner and disposition. **Pause** means a control is implemented but evidence is incomplete. **No-go** means an unauthorized read/write, PHI telemetry leak, incomplete deletion, broken revocation boundary, unrotated key, or missing audit event was observed. The recommendation is not a clinical safety determination and does not authorize production PHI by itself.
