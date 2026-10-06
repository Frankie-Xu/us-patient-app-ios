#!/bin/sh
set -eu

: "${STAGING_S3_ENDPOINT:?STAGING_S3_ENDPOINT is required}"
: "${STAGING_S3_ACCESS_KEY:?STAGING_S3_ACCESS_KEY is required}"
: "${STAGING_S3_SECRET_KEY:?STAGING_S3_SECRET_KEY is required}"
: "${STAGING_S3_BUCKET:?STAGING_S3_BUCKET is required}"

mc alias set staging "$STAGING_S3_ENDPOINT" "$STAGING_S3_ACCESS_KEY" "$STAGING_S3_SECRET_KEY" >/dev/null
mc mb --ignore-existing "staging/$STAGING_S3_BUCKET" >/dev/null
mc stat "staging/$STAGING_S3_BUCKET" >/dev/null
