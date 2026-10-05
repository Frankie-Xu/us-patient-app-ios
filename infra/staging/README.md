# Real staging composition

This directory defines a reproducible, synthetic/de-identified staging
composition. It starts PostgreSQL, MinIO (S3-compatible), Redis, the current
API HTTP adapter, and a metadata-only worker health boundary. It does not claim
that the current API has production PostgreSQL, S3, or Redis adapters: the
checked-in API still uses its provider-neutral local runtime until those
adapters are approved and implemented behind the existing protocols.

## Start

Create a local env file from the checked-in example and replace all placeholder
secrets using the approved secret manager or shell environment:

```sh
cp .env.staging.example .env.staging
chmod 600 .env.staging
scripts/staging/compose-up.sh
```

The helper requires `STAGING_ENV_FILE` when the env file lives elsewhere. It
never prints secret values. API health is available at
`http://localhost:58000/healthz`; worker health is available at
`http://localhost:58001/healthz` with the example ports.

Stop the services without deleting data with:

```sh
scripts/staging/compose-down.sh
```

Set `STAGING_REMOVE_VOLUMES=1` only when synthetic staging data should be
deleted. The default is to preserve the three named volumes.

## Validation

Validate interpolation without starting containers:

```sh
docker compose --env-file .env.staging.example \
  --file infra/staging/compose.yaml config --quiet
scripts/staging/test-compose.sh
```

When Docker Desktop/daemon is unavailable, this config check remains useful;
`compose-up.sh` should be run only after the daemon is running. The API image
uses deterministic synthetic fixtures and `AI_PROVIDER=stub` by default. No
real patient content, tokens, production URLs, or cloud credentials belong in
this repository.
