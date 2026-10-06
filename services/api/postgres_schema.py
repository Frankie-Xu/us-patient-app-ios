"""Migration seam for the PostgreSQL staging schema.

The API core stays provider-neutral. A deployment can inject a psycopg or
another DB-API connection into this runner without importing a driver into the
offline test package. Migration SQL is intentionally kept as reviewed files
under migrations/postgres and contains metadata/object references only.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


MIGRATION_DIR = Path(__file__).with_name("migrations") / "postgres"


class MigrationConnection(Protocol):
    def execute(self, statement: str, parameters: tuple[Any, ...] | None = None) -> Any:
        """Execute one statement using a DB-API compatible connection."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str


def load_migrations(directory: Path = MIGRATION_DIR) -> tuple[Migration, ...]:
    """Load reviewed SQL migrations in ascending version order."""
    migrations: list[Migration] = []
    for path in sorted(directory.glob("*.sql")):
        prefix, separator, name = path.name.partition("_")
        if not separator or not prefix.isdigit():
            raise ValueError("migration names must start with a numeric version")
        migrations.append(Migration(int(prefix), name.removesuffix(".sql"), path.read_text(encoding="utf-8")))
    versions = [migration.version for migration in migrations]
    if len(versions) != len(set(versions)):
        raise ValueError("migration versions must be unique")
    return tuple(migrations)


class PostgresMigrationRunner:
    """Apply migrations without making a driver choice for the service."""

    def __init__(self, connection: MigrationConnection, *, migrations: tuple[Migration, ...] | None = None) -> None:
        self.connection = connection
        self.migrations = migrations or load_migrations()

    def apply(self) -> tuple[int, ...]:
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        applied_rows = self.connection.execute("SELECT version FROM schema_migrations ORDER BY version")
        applied = {int(row[0]) for row in (applied_rows.fetchall() if hasattr(applied_rows, "fetchall") else applied_rows)}
        applied_now: list[int] = []
        for migration in self.migrations:
            if migration.version in applied:
                continue
            self.connection.execute(migration.sql)
            self.connection.execute(
                "INSERT INTO schema_migrations(version, name) VALUES (%s, %s)",
                (migration.version, migration.name),
            )
            applied_now.append(migration.version)
        commit = getattr(self.connection, "commit", None)
        if callable(commit):
            commit()
        return tuple(applied_now)
