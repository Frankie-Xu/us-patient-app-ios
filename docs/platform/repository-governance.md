# Repository governance

This document is the versioned operating contract for the repository. GitHub
branch protection, Actions defaults, secret scanning, and access controls remain
settings that must be reviewed in the repository UI; this file records the
behavior those settings must enforce.

## Branches and pull requests

- `main` is the only integration and release branch. Feature work branches from
  `main` and uses `feat/<area>-<short-name>`, `fix/<area>-<short-name>`, or
  `docs/<short-name>`.
- Every pull-request head and stacked base branch follows the checked branch
  policy: `feat/`, `fix/`, `docs/`, `chore/`, `test/`, `refactor/`, `ci/`,
  `perf/`, or an approved `dependabot/` branch. Legacy branches remain visible
  until their active work is closed or migrated.
- Prefer one concern per pull request. A stacked pull request is allowed only
  when it has a clear parent PR link, a `stacked` label, and an update plan.
- Every PR uses the checked-in template and identifies user-visible behavior,
  requirement or ADR, validation, privacy impact, and remaining decisions.
- A PR is ready to merge only when required CI checks are green, conversations
  are resolved, the owning area has reviewed the boundary, and the author has
  confirmed that no PHI, credentials, or vendor payloads are present.
- Keep `main` protected against force pushes and deletion. Require the
  `Integration gate` status check and review from Code Owners once a second
  maintainer is available. Dismiss stale approvals after new commits.

## Ownership

`.github/CODEOWNERS` is the source of truth for review routing. The repository
keeps explicit ownership for iOS, API, AI, contracts, scripts, documentation,
and GitHub configuration. When a second maintainer joins, add them to the
relevant sensitive areas before increasing the required approval count.

## Dependencies and CI

- Dependabot checks GitHub Actions, the API's pip dependencies, and the iOS
  Swift package surface weekly.
- GitHub Actions use full commit SHAs, least-privilege permissions, and
  `persist-credentials: false` on checkout.
- Pull requests always run repository validation and the integration gate.
  API, AI, contract, and iOS suites run when their boundary changes; shared
  script or CI changes fan out to the full suite so the fast path stays fast
  without weakening coverage where it matters.
- `bash scripts/verify.sh --quick` is the local iteration gate. The full gate
  is required before review and produces the same redacted evidence shape as CI.
- Runtime dependency changes must preserve reproducibility. Keep application
  dependency ranges intentional and add a lock or constraints file before a
  production deployment depends on them.

## Issues and maintenance

- Use the bug or feature template. Security reports go through a private
  advisory and never through a public issue.
- During weekly triage, assign an owner, add an area and priority label, link a
  requirement or ADR, and close duplicates or superseded work.
- Review open branches and stacked PRs monthly. Delete branches after merge or
  closure unless they are explicitly retained for release or audit evidence.
- Keep branches unprotected by default so short-lived development stays fast;
  enforce the policy through pull-request CI and protect integration branches.
- Review CODEOWNERS, Actions permissions, Dependabot coverage, and repository
  access quarterly.

## Privacy and release

Assume every committed file, branch, issue, PR, log, and CI artifact is public.
Use synthetic or appropriately de-identified fixtures only. Release from a
green `main` commit with a semantic-version tag, redacted evidence, tested
component versions, migration notes, and rollback steps. Production PHI stays
behind the security and evidence gates documented in the ADRs.
