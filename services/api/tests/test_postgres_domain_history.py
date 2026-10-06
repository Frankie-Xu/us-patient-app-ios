from pathlib import Path
import re

import pytest

MIGRATION_DIR = Path(__file__).parents[1] / "migrations" / "postgres"
MIGRATION = MIGRATION_DIR / "0002_domain_history.sql"
README = MIGRATION_DIR / "README.md"

EXPECTED_TABLES = (
    "users",
    "patients",
    "cases",
    "case_documents",
    "case_facts",
    "fact_reviews",
    "document_history",
    "account_history",
    "case_history",
)

def test_domain_migration_follows_foundation_in_numeric_order():
    versions = sorted(
        int(path.name.split("_", 1)[0])
        for path in MIGRATION_DIR.glob("*.sql")
        if path.name.split("_", 1)[0].isdigit()
    )
    assert versions == [1, 2]
    assert MIGRATION.exists()
    assert "0001_initial.sql" in README.read_text(encoding="utf-8")

def test_domain_tables_are_idempotent_and_have_opaque_constraints():
    sql = MIGRATION.read_text(encoding="utf-8")
    for table in EXPECTED_TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS users_subject_ref_uidx" in sql
    assert "UNIQUE (account_id, patient_ref)" in sql
    assert "UNIQUE (account_id, case_ref)" in sql
    assert "UNIQUE (fact_id, review_version)" in sql
    assert "UNIQUE (document_id, document_version, event_type, event_ref)" in sql
    assert "UNIQUE (account_id, event_type, event_ref)" in sql
    assert "UNIQUE (case_id, event_type, event_ref)" in sql
    assert "REFERENCES document_versions(document_id, version)" in sql
    assert "raw document bytes" in sql.lower()
    assert "bytea" not in sql.lower()
    assert "raw_bytes" not in sql.lower()
    assert re.search(r"patient_ref TEXT NOT NULL\s+CHECK", sql)
    assert re.search(r"case_ref TEXT NOT NULL\s+CHECK", sql)

def test_history_rows_are_protected_from_update_and_delete():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "CREATE OR REPLACE FUNCTION prevent_history_mutation()" in sql
    assert "RAISE EXCEPTION 'append-only history records cannot be updated or deleted'" in sql
    for table in ("fact_reviews", "document_history", "account_history", "case_history"):
        assert f"DROP TRIGGER IF EXISTS {table}_append_only" in sql
        assert f"BEFORE UPDATE OR DELETE ON {table}" in sql
        assert f"FOR EACH ROW EXECUTE FUNCTION prevent_history_mutation()" in sql

def test_sql_dollar_quoted_function_and_transaction_are_balanced():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert sql.count("BEGIN;") == 1
    assert sql.count("COMMIT;") == 1
    assert sql.count("$$") == 2
    assert sql.count("CREATE OR REPLACE FUNCTION") == 1

def test_sql_has_no_unbounded_or_direct_identifier_columns():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    forbidden = (" raw_content ", " content bytea", " full_name ", " date_of_birth ", " address ")
    assert not any(token in sql for token in forbidden)

@pytest.mark.parametrize("path", [MIGRATION, README])
def test_domain_artifacts_are_utf8_text(path):
    path.read_text(encoding="utf-8")
