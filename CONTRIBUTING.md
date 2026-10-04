# Contributing

## Branches and commits

- Branch from `main` using `feat/<area>-<short-name>`, `fix/<area>-<short-name>`, or `docs/<short-name>`.
- Keep commits focused and use Conventional Commits: `feat(ios): ...`, `fix(api): ...`, `test(ai): ...`, `docs: ...`.
- Do not commit credentials, real patient data, access tokens, exported PDFs, screenshots containing health information, or vendor payloads.

## Pull requests

Every pull request should state the user-visible behavior, linked requirement or decision, validation performed, data/privacy impact, and any remaining decision. Keep generated code changes separate from hand-written contract changes when practical.

Required before merge:

- CI is green. A skipped component is acceptable only when its source and tests are not present; record the skip in the pull request.
- Tests cover the changed boundary, or the pull request explains why no automated test is available.
- API and data-contract changes are reviewed by the owning area.
- iOS flows include empty, loading, failure, retry, permission, and success states.
- AI changes include a de-identified golden-set evaluation and a high-severity error review.
- The pull request contains no PHI, credentials, vendor payloads, or copied clinical text.

## Release expectations

- Release from a green `main` commit after the pull request checks and required reviews are complete.
- Use an annotated semantic-version tag (`vMAJOR.MINOR.PATCH`) and describe user-visible changes, migrations, dependency updates, and rollback steps.
- Confirm the release contains no credentials, PHI, clinical documents, unredacted logs, or real vendor responses. Release notes and attached artifacts follow the same rule.
- Record the tested iOS/API/AI versions and any intentionally skipped component before publishing.
- Use short-lived, least-privilege credentials only in the deployment environment; never add them to repository files or release artifacts.

## PHI-safe logging

Logs, traces, crash reports, test output, screenshots, analytics events, and pull request text must not contain names, dates of birth, medical record numbers, diagnoses, medications, free-text notes, OCR text, document contents, signed URLs, authorization headers, or access tokens.

Log request IDs, operation names, status codes, elapsed time, counts, and stable non-reversible identifiers instead. Redact query strings, headers, filenames, and exception payloads at the logging boundary. Test fixtures and test names use synthetic labels. A failure should identify the component and rule that failed without printing the protected value.

## Review language

Review facts, behavior, failure modes, privacy boundaries, and maintainability. Do not paste protected medical content into issues, pull requests, logs, or chat.
