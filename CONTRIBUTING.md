# Contributing

## Branches and commits

- Branch from `main` using `feat/<area>-<short-name>`, `fix/<area>-<short-name>`, or `docs/<short-name>`.
- Keep commits focused and use Conventional Commits: `feat(ios): ...`, `fix(api): ...`, `test(ai): ...`, `docs: ...`.
- Do not commit credentials, real patient data, access tokens, exported PDFs, screenshots containing health information, or vendor payloads.

## Pull requests

Every pull request should state the user-visible behavior, linked requirement or decision, validation performed, data/privacy impact, and any remaining decision. Keep generated code changes separate from hand-written contract changes when practical.

Required before merge:

- CI is green.
- Tests cover the changed boundary.
- API and data-contract changes are reviewed by the owning area.
- iOS flows include empty, loading, failure, retry, permission, and success states.
- AI changes include a golden-set evaluation and a high-severity error review.

## Review language

Review facts, behavior, failure modes, privacy boundaries, and maintainability. Do not paste protected medical content into issues, pull requests, logs, or chat.

