"""SQLite schema-version guardrails for local durable adapters.

The helper provides a small, provider-neutral migration boundary. SQLite is
used only for local/staging contract tests; production adapters must use their
managed migration system and reviewed rollback procedure.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Callable


class UnsupportedSchemaVersionError(RuntimeError):
    """Raised when a database is newer than the adapter understands."""


def ensure_schema_version(
    connection: sqlite3.Connection,
    *,
    current_version: int,
    initialize: Callable[[sqlite3.Connection], None],
) -> None:
    """Initialize or validate a database schema without downgrading it.

    A version of zero is the legacy/fresh state used by the Phase 14 adapters.
    It is initialized in place and promoted to the current version. Any future
    version fails closed so an older binary cannot silently mutate a database.
    """
    if current_version < 1:
        raise ValueError("schema version must be positive")

    row = connection.execute("PRAGMA user_version").fetchone()
    version = int(row[0]) if row else 0
    if version > current_version:
        raise UnsupportedSchemaVersionError("database schema is newer than this adapter")
    if version not in (0, current_version):
        raise UnsupportedSchemaVersionError("database schema migration is required")

    with connection:
        initialize(connection)
        if version == 0:
            connection.execute(f"PRAGMA user_version = {current_version}")
