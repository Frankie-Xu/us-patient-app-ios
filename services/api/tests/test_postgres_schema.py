from pathlib import Path

from services.api.postgres_schema import PostgresMigrationRunner, load_migrations


class FakeResult:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def fetchall(self):
        return list(self.rows)


class FakeConnection:
    def __init__(self):
        self.statements = []
        self.committed = False
        self._schema_rows = []

    def execute(self, statement, parameters=None):
        self.statements.append((statement, parameters))
        if statement.startswith("SELECT version"):
            return FakeResult(self._schema_rows)
        if statement.startswith("INSERT INTO schema_migrations"):
            self._schema_rows.append((parameters[0],))
        return FakeResult()

    def commit(self):
        self.committed = True


def test_postgres_migrations_are_sorted_and_apply_once():
    migrations = load_migrations()
    assert migrations
    expected_versions = tuple(migration.version for migration in migrations)
    assert list(expected_versions) == sorted(expected_versions)
    assert Path("services/api/migrations/postgres/0001_initial.sql").exists()

    connection = FakeConnection()
    runner = PostgresMigrationRunner(connection, migrations=migrations)
    assert runner.apply() == expected_versions
    assert runner.apply() == ()
    assert connection.committed is True
