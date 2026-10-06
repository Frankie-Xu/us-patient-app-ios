#!/bin/sh
set -eu

: "${STAGING_POSTGRES_DB:?STAGING_POSTGRES_DB is required}"
: "${STAGING_POSTGRES_USER:?STAGING_POSTGRES_USER is required}"
: "${STAGING_POSTGRES_PASSWORD:?STAGING_POSTGRES_PASSWORD is required}"

export PGHOST="${PGHOST:-postgres}"
export PGPORT="${PGPORT:-5432}"
export PGDATABASE="$STAGING_POSTGRES_DB"
export PGUSER="$STAGING_POSTGRES_USER"
export PGPASSWORD="$STAGING_POSTGRES_PASSWORD"

test -f /state/migration.ready
until pg_isready -q; do
  sleep 1
done

queue_table="$(psql -Atqc "SELECT to_regclass('public.processing_jobs')")"
test "$queue_table" = "processing_jobs"
