# PostgreSQL domain persistence

Migration `0002_domain_history.sql` depends on `0001_initial.sql` from the
staging backend foundation. The migration is safe to run repeatedly: tables and
indexes use `IF NOT EXISTS`, the guard function is replaced deterministically,
and append-only triggers are dropped/recreated with stable names.

The tables contain only opaque account, patient, case, document, and event
references. They do not contain names, dates of birth, addresses, raw document
bytes, OCR payloads, or object-store content. Document bytes remain in the
S3-compatible adapter introduced by the foundation migration.

## Tables and boundaries

- `users` and `patients` hold account-scoped opaque references.
- `cases` owns a versioned patient record; `case_documents` and
  `case_facts` connect existing documents/facts without changing their
  contracts.
- `fact_reviews` records each review decision and source span as a new row.
- `document_history`, `account_history`, and `case_history` record
  idempotent event references with JSON metadata.
- Foreign keys retain document versions and facts while preventing history rows
  from becoming detached.
- History and review rows are append-only. The trigger rejects UPDATE and
  DELETE; corrections must be represented by another event/review row.

The provider-neutral migration runner discovers this file by its numeric prefix
and records version 2 in `schema_migrations`. Apply the migration only after
`0001_initial.sql` has created `documents`, `document_versions`, and
`facts`.
