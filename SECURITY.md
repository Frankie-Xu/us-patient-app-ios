# Security policy

This private repository handles product code and de-identified fixtures only. Never report a vulnerability with patient records, credentials, access tokens, or unredacted vendor responses.

## Reporting

Use a private GitHub security advisory or contact the repository owner through a trusted private channel. Include a minimal reproduction, affected commit, impact, and a redacted proof. Do not open a public issue for a suspected authorization, data exposure, or credential problem.

## Product security rules

- Treat documents, extracted facts, summaries, tasks, share links, and audit events as sensitive by default.
- Keep PHI out of telemetry, crash reports, debug logs, fixtures, screenshots, analytics events, test names, release notes, and CI output.
- Keep logs limited to request IDs, operation names, status, duration, counts, and stable non-reversible identifiers. Redact headers, query strings, filenames, exception payloads, OCR text, and document bodies at the logging boundary.
- Use short-lived credentials, least-privilege service roles, encrypted transport and protected storage.
- Revoke or rotate exposed credentials immediately; record the incident without copying the secret.
- Run `scripts/validate-repo.sh` before committing. It checks credential patterns, clinical-document formats, and common PHI labels while redacting matched values in failure output.
