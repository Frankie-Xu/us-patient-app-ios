"""Compose entrypoint that wires the API to staging provider adapters.

The framework-neutral API remains unchanged. This module is the deployment
composition only: it reads provider endpoints from the environment, applies
the checked-in PostgreSQL migration, and injects the Postgres, S3-compatible,
and Redis implementations behind the existing protocols. Startup fails closed
if a provider or required setting is unavailable.
"""
from __future__ import annotations

import os

from services.api.app import create_app
from services.api.provider_adapters import PostgresMetadataStore, ProviderSettings, RedisJobQueue, S3ObjectStore
from services.api.service import ApiService


def _required(settings: ProviderSettings) -> None:
    missing = []
    if not settings.postgres_dsn:
        missing.append("DATABASE_URL")
    if not settings.s3_bucket:
        missing.append("S3_BUCKET")
    if not settings.s3_endpoint:
        missing.append("S3_ENDPOINT")
    if not settings.redis_url:
        missing.append("REDIS_URL")
    if missing:
        raise RuntimeError("staging provider settings are missing: " + ", ".join(missing))


def build_app():
    settings = ProviderSettings.from_environment()
    _required(settings)
    metadata = PostgresMetadataStore(settings.postgres_dsn or "")
    try:
        objects = S3ObjectStore(
            settings.s3_bucket or "",
            endpoint_url=settings.s3_endpoint,
            region_name=settings.s3_region,
        )
        queue = RedisJobQueue(
            settings.redis_url or "",
            queue_name=settings.redis_queue,
        )
    except Exception:
        metadata.close()
        raise
    service = ApiService(store=metadata, object_store=objects, job_queue=queue)
    return create_app(service)


if os.getenv("APP_ENV", "staging").lower() != "local":
    app = build_app()
else:  # Keep an explicit local escape hatch for dependency-free development.
    from services.api.app import app  # type: ignore[no-redef]
