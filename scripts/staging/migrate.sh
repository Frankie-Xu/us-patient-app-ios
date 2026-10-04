#!/bin/sh
set -eu

: "${STAGING_POSTGRES_DB:?STAGING_POSTGRES_DB is required}"
: "${STAGING_POSTGRES_USER:?STAGING_POSTGRES_USER is required}"
: "${STAGING_POSTGRES_PASSWORD:?STAGING_POSTGRES_PASSWORD is required}"
: "${STAGING_MIGRATION_VERSION:?STAGING_MIGRATION_VERSION is required}"
: "${STAGING_MIGRATION_NAME:?STAGING_MIGRATION_NAME is required}"

export PGHOST="${PGHOST:-postgres}"
export PGPORT="${PGPORT:-5432}"
export PGDATABASE="$STAGING_POSTGRES_DB"
export PGUSER="$STAGING_POSTGRES_USER"
export PGPASSWORD="$STAGING_POSTGRES_PASSWORD"

until pg_isready -q; do
  sleep 1
done

psql -v ON_ERROR_STOP=1 -f /migrations/0001_initial.sql
psql -v ON_ERROR_STOP=1 \
  -v migration_version="$STAGING_MIGRATION_VERSION" \
  -v migration_name="$STAGING_MIGRATION_NAME" \
  -c "INSERT INTO schema_migrations(version, name)
      VALUES (:'migration_version'::integer, :'migration_name')
      ON CONFLICT (version) DO UPDATE
      SET name = EXCLUDED.name"
touch /state/migration.ready
