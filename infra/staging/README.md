# Staging infrastructure seam

This composition starts only the stateful dependencies required for a staging
rehearsal: PostgreSQL 16 and an S3-compatible MinIO endpoint. It contains no
API image, credentials, PHI, or production DNS. The API process should inject a
DB-API connection, S3ObjectStore, and a processing worker queue through its
deployment configuration.

## Local rehearsal

1. Copy .env.example to .env and replace every placeholder locally.
2. Start the dependencies with docker compose --env-file .env up -d.
3. Confirm PostgreSQL and MinIO health before starting the API.
4. Apply reviewed migrations through PostgresMigrationRunner or the deployment migration job.
5. Configure the API with the MinIO endpoint and a short-lived staging bucket.
6. Use synthetic documents only. Destroy named volumes after the rehearsal.

The migration directory is mounted read-only and can be reviewed independently.
The queue table is metadata-only; workers fetch bytes by internal object key and
must not place raw content in queue payloads or logs.
