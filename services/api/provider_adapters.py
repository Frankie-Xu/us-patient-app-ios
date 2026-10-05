"""Optional staging provider adapters.

The core API only depends on the provider-neutral ``MetadataStore``,
``ObjectStore`` and ``JobQueue`` protocols.  This module provides adapters for
the services used by a staging deployment without making those SDKs mandatory
for the dependency-free local test suite.  Constructors accept an injected
client/connection for deterministic tests; production callers should pass a
DSN or endpoint and let the provider SDK resolve credentials from its normal
environment/identity chain.

No request payload, token, or credential is logged by these adapters.  Queue
messages contain metadata only; document bytes stay in object storage.
"""
from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .dependencies import DependencyUnavailableError, JobQueue, ObjectStore
from .store import (
    IdempotencyConflictError,
    MetadataStore,
    NotFoundError,
    VersionConflictError,
    _decode_model,
    _decode_storage,
    _encode_storage,
)
from .models import AuditEvent, IdempotencyRecord


@dataclass(frozen=True)
class ProviderSettings:
    """Provider endpoints loaded from environment without exposing secrets."""

    postgres_dsn: str | None = None
    s3_bucket: str | None = None
    s3_endpoint: str | None = None
    s3_region: str = "us-east-1"
    redis_url: str | None = None
    redis_queue: str = "patient-app-processing"

    @classmethod
    def from_environment(cls, env: Mapping[str, str] | None = None) -> "ProviderSettings":
        values = os.environ if env is None else env
        return cls(
            postgres_dsn=values.get("DATABASE_URL") or values.get("POSTGRES_DSN"),
            s3_bucket=values.get("S3_BUCKET"),
            s3_endpoint=values.get("S3_ENDPOINT") or values.get("AWS_ENDPOINT_URL"),
            s3_region=values.get("AWS_REGION", "us-east-1"),
            redis_url=values.get("REDIS_URL"),
            redis_queue=values.get("REDIS_QUEUE", "patient-app-processing"),
        )


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _decode_json(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    return json.loads(value) if isinstance(value, str) else value


def _load_migration() -> str:
    path = Path(__file__).with_name("migrations") / "001_provider_adapters.sql"
    return path.read_text(encoding="utf-8")


@contextmanager
def _transaction(connection: Any):
    """Use psycopg3's transaction context and psycopg2's connection context."""
    transaction = getattr(connection, "transaction", None)
    if callable(transaction):
        with transaction():
            yield
    else:
        with connection:
            yield


class PostgresMetadataStore:
    """PostgreSQL implementation of :class:`MetadataStore`.

    ``psycopg`` (v3) is preferred and ``psycopg2`` is accepted for existing
    deployments.  The import is intentionally lazy so local tests remain
    runnable without either package or a database daemon.
    """

    def __init__(
        self,
        dsn: str,
        *,
        connection_factory: Callable[[str], Any] | None = None,
        available: bool = True,
        apply_migrations: bool = True,
    ) -> None:
        if not dsn or not dsn.strip():
            raise ValueError("postgres DSN is required")
        self.dsn = dsn
        self.available = available
        self._connection_factory = connection_factory
        self._connection: Any | None = None
        if available:
            try:
                self._connection = self._connect()
                if apply_migrations:
                    with self._connection.cursor() as cursor:
                        cursor.execute(_load_migration())
                    self._connection.commit()
            except Exception as exc:
                self.close()
                raise DependencyUnavailableError("metadata store is unavailable") from exc

    def _connect(self) -> Any:
        if self._connection_factory is not None:
            return self._connection_factory(self.dsn)
        try:
            import psycopg  # type: ignore[import-not-found]

            return psycopg.connect(self.dsn)
        except ModuleNotFoundError:
            try:
                import psycopg2  # type: ignore[import-not-found]

                return psycopg2.connect(self.dsn)
            except ModuleNotFoundError as exc:
                raise DependencyUnavailableError("install the staging postgres extra") from exc

    def _require_connection(self) -> Any:
        if not self.available or self._connection is None:
            raise DependencyUnavailableError("metadata store is unavailable")
        return self._connection

    def is_ready(self) -> bool:
        try:
            connection = self._require_connection()
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            return True
        except Exception:
            return False

    def get_resource(self, resource_type: str, identifier: str) -> Any:
        connection = self._require_connection()
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT payload FROM metadata_resources WHERE resource_type = %s AND identifier = %s",
                (resource_type, identifier),
            )
            row = cursor.fetchone()
        if row is None:
            raise NotFoundError("resource not found")
        payload = _decode_json(row[0])
        return _decode_model(resource_type, _json(payload))

    def list_resources(self, resource_type: str) -> list[Any]:
        connection = self._require_connection()
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT payload FROM metadata_resources WHERE resource_type = %s ORDER BY identifier",
                (resource_type,),
            )
            rows = cursor.fetchall()
        return [_decode_model(resource_type, _json(_decode_json(row[0]))) for row in rows]

    def save_resource(self, resource_type: str, value: Any, expected_version: int | None = None) -> Any:
        connection = self._require_connection()
        identifier = str(getattr(value, "id", ""))
        if not identifier:
            raise ValueError("resource id is required")
        versioned = hasattr(value, "version")
        version = int(getattr(value, "version", 1))
        owner_id = str(getattr(value, "owner_id", ""))
        payload = _json(_encode_storage(value))
        try:
            with _transaction(connection):
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT version FROM metadata_resources WHERE resource_type = %s AND identifier = %s FOR UPDATE",
                        (resource_type, identifier),
                    )
                    row = cursor.fetchone()
                    if row is not None:
                        actual = int(row[0])
                        if expected_version is not None and actual != expected_version:
                            raise VersionConflictError("expected version does not match current version")
                        if versioned and version <= actual:
                            raise VersionConflictError("updated version must be greater than current version")
                        if not versioned:
                            version = actual
                        cursor.execute(
                            "UPDATE metadata_resources SET owner_id = %s, version = %s, payload = %s, updated_at = NOW() WHERE resource_type = %s AND identifier = %s",
                            (owner_id, version, payload, resource_type, identifier),
                        )
                    else:
                        if expected_version not in (None, 0):
                            raise VersionConflictError("expected version supplied for a new resource")
                        cursor.execute(
                            "INSERT INTO metadata_resources(resource_type, identifier, owner_id, version, payload) VALUES (%s, %s, %s, %s, %s)",
                            (resource_type, identifier, owner_id, version, payload),
                        )
            return value
        except (VersionConflictError, IdempotencyConflictError):
            raise
        except Exception as exc:
            raise DependencyUnavailableError("metadata store is unavailable") from exc

    def append_audit(self, event: AuditEvent) -> None:
        connection = self._require_connection()
        payload = _json(_encode_storage(event))
        try:
            with _transaction(connection):
                with connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO audit_events(identifier, payload) VALUES (%s, %s) ON CONFLICT (identifier) DO NOTHING",
                        (event.id, payload),
                    )
        except Exception as exc:
            raise DependencyUnavailableError("metadata store is unavailable") from exc

    def list_audit_events(self) -> list[AuditEvent]:
        connection = self._require_connection()
        with connection.cursor() as cursor:
            cursor.execute("SELECT payload FROM audit_events ORDER BY identifier")
            rows = cursor.fetchall()
        return [_decode_storage(_decode_json(row[0]), AuditEvent) for row in rows]

    def remember_idempotency(self, record: IdempotencyRecord) -> None:
        connection = self._require_connection()
        payload = _json(_encode_storage(record))
        try:
            with _transaction(connection):
                with connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO idempotency(actor_id, idempotency_key, payload) VALUES (%s, %s, %s) ON CONFLICT (actor_id, idempotency_key) DO UPDATE SET payload = EXCLUDED.payload",
                        (record.actor_id, record.key, payload),
                    )
        except Exception as exc:
            raise DependencyUnavailableError("metadata store is unavailable") from exc

    def get_idempotency(self, actor_id: str, key: str) -> IdempotencyRecord | None:
        connection = self._require_connection()
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT payload FROM idempotency WHERE actor_id = %s AND idempotency_key = %s",
                (actor_id, key),
            )
            row = cursor.fetchone()
        return None if row is None else _decode_storage(_decode_json(row[0]), IdempotencyRecord)

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> "PostgresMetadataStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class S3ObjectStore:
    """S3-compatible object storage adapter with checksum-based idempotency."""

    def __init__(
        self,
        bucket: str,
        *,
        endpoint_url: str | None = None,
        region_name: str = "us-east-1",
        prefix: str = "uploads",
        client: Any | None = None,
        client_factory: Callable[..., Any] | None = None,
        available: bool = True,
    ) -> None:
        if not bucket.strip():
            raise ValueError("S3 bucket is required")
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.available = available
        self._client = client
        if available and self._client is None:
            try:
                if client_factory is not None:
                    self._client = client_factory(endpoint_url=endpoint_url, region_name=region_name)
                else:
                    import boto3  # type: ignore[import-not-found]

                    self._client = boto3.client("s3", endpoint_url=endpoint_url, region_name=region_name)
            except ModuleNotFoundError as exc:
                raise DependencyUnavailableError("install the staging object-storage extra") from exc

    def _require_client(self) -> Any:
        if not self.available or self._client is None:
            raise DependencyUnavailableError("object store is unavailable")
        return self._client

    def _key(self, key: str) -> str:
        clean = key.strip().lstrip("/")
        if not clean:
            raise ValueError("object-store key is required")
        return f"{self.prefix}/{clean}" if self.prefix else clean

    @staticmethod
    def _not_found(exc: Exception) -> bool:
        response = getattr(exc, "response", None) or {}
        code = str((response.get("Error") or {}).get("Code", ""))
        return code in {"404", "NoSuchKey", "NotFound"}

    def is_ready(self) -> bool:
        try:
            self._require_client().head_bucket(Bucket=self.bucket)
            return True
        except Exception:
            return False

    def put(self, key: str, content: bytes, *, media_type: str) -> str:
        client = self._require_client()
        if not isinstance(content, bytes):
            raise TypeError("object-store content must be bytes")
        object_key = self._key(key)
        digest = hashlib.sha256(content).hexdigest()
        try:
            existing = client.head_object(Bucket=self.bucket, Key=object_key)
            metadata = {str(k).lower(): str(v) for k, v in (existing.get("Metadata") or {}).items()}
            if metadata.get("sha256") == digest:
                return key
            raise IdempotencyConflictError("object key already contains different content")
        except IdempotencyConflictError:
            raise
        except Exception as exc:
            if not self._not_found(exc):
                raise DependencyUnavailableError("object store is unavailable") from exc
        try:
            client.put_object(
                Bucket=self.bucket,
                Key=object_key,
                Body=content,
                ContentType=media_type,
                Metadata={"sha256": digest},
            )
            return key
        except Exception as exc:
            raise DependencyUnavailableError("object store is unavailable") from exc

    def get(self, key: str) -> bytes:
        try:
            result = self._require_client().get_object(Bucket=self.bucket, Key=self._key(key))
            body = result["Body"]
            return bytes(body.read())
        except Exception as exc:
            if self._not_found(exc):
                raise KeyError("object not found") from exc
            raise DependencyUnavailableError("object store is unavailable") from exc


class RedisJobQueue:
    """Redis list queue with SETNX-based job idempotency."""

    def __init__(
        self,
        url: str,
        *,
        queue_name: str = "patient-app-processing",
        client: Any | None = None,
        client_factory: Callable[[str], Any] | None = None,
        available: bool = True,
    ) -> None:
        if not url.strip():
            raise ValueError("redis URL is required")
        if not queue_name.strip():
            raise ValueError("redis queue name is required")
        self.url = url
        self.queue_name = queue_name
        self.available = available
        self._client = client
        if available and self._client is None:
            try:
                if client_factory is not None:
                    self._client = client_factory(url)
                else:
                    import redis  # type: ignore[import-not-found]

                    self._client = redis.Redis.from_url(url, decode_responses=True)
            except ModuleNotFoundError as exc:
                raise DependencyUnavailableError("install the staging redis extra") from exc

    def _require_client(self) -> Any:
        if not self.available or self._client is None:
            raise DependencyUnavailableError("job queue is unavailable")
        return self._client

    def _marker(self, job_id: str) -> str:
        return f"{self.queue_name}:job:{job_id}"

    def is_ready(self) -> bool:
        try:
            return bool(self._require_client().ping())
        except Exception:
            return False

    def enqueue(self, job_id: str, payload: Mapping[str, str]) -> None:
        if not job_id.strip():
            raise ValueError("job id is required")
        safe = {str(key): str(value) for key, value in payload.items()}
        message = _json({"job_id": job_id, "payload": safe})
        client = self._require_client()
        marker = self._marker(job_id)
        try:
            # SETNX is the durable idempotency gate.  The marker is written
            # before the list append so retries cannot enqueue a second copy;
            # workers can inspect the marker when recovering a failed append.
            inserted = bool(client.set(marker, message, nx=True))
            if inserted:
                try:
                    client.rpush(self.queue_name, message)
                except Exception:
                    # Allow a retry after a transient append failure.
                    client.delete(marker)
                    raise
            else:
                inserted = False
            if not inserted:
                existing = client.get(marker)
                if existing is not None and _decode_json(existing) != _decode_json(message):
                    raise IdempotencyConflictError("job id already contains different payload")
        except IdempotencyConflictError:
            raise
        except Exception as exc:
            raise DependencyUnavailableError("job queue is unavailable") from exc

    @property
    def entries(self) -> list[tuple[str, dict[str, str]]]:
        try:
            raw = self._require_client().lrange(self.queue_name, 0, -1)
            entries = []
            for item in raw:
                decoded = _decode_json(item)
                entries.append((str(decoded["job_id"]), dict(decoded["payload"])))
            return entries
        except Exception as exc:
            raise DependencyUnavailableError("job queue is unavailable") from exc
