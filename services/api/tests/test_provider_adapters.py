from __future__ import annotations

import unittest

from services.api.dependencies import DependencyUnavailableError
from services.api.provider_adapters import (
    PostgresMetadataStore,
    ProviderSettings,
    RedisJobQueue,
    S3ObjectStore,
)
from services.api.store import IdempotencyConflictError


class _NotFound(Exception):
    response = {"Error": {"Code": "404"}}


class _Body:
    def __init__(self, value: bytes) -> None:
        self.value = value

    def read(self) -> bytes:
        return self.value


class _FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, dict[str, str]]] = {}

    def head_bucket(self, **_: object) -> None:
        return None

    def head_object(self, *, Key: str, **_: object) -> dict[str, object]:
        try:
            _, metadata = self.objects[Key]
        except KeyError as exc:
            raise _NotFound() from exc
        return {"Metadata": metadata}

    def put_object(self, *, Key: str, Body: bytes, Metadata: dict[str, str], **_: object) -> None:
        self.objects[Key] = (Body, Metadata)

    def get_object(self, *, Key: str, **_: object) -> dict[str, object]:
        try:
            body, _ = self.objects[Key]
        except KeyError as exc:
            raise _NotFound() from exc
        return {"Body": _Body(body)}


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}

    def ping(self) -> bool:
        return True

    def set(self, key: str, value: str, *, nx: bool = False) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def delete(self, key: str) -> int:
        return int(self.values.pop(key, None) is not None)

    def rpush(self, key: str, value: str) -> int:
        self.lists.setdefault(key, []).append(value)
        return len(self.lists[key])

    def lrange(self, key: str, start: int, end: int) -> list[str]:
        values = self.lists.get(key, [])[start : None if end == -1 else end + 1]
        return values


class ProviderSettingsTests(unittest.TestCase):
    def test_environment_settings_do_not_require_credentials(self) -> None:
        settings = ProviderSettings.from_environment(
            {
                "DATABASE_URL": "postgresql://staging.invalid/patient",
                "S3_BUCKET": "patient-staging",
                "AWS_ENDPOINT_URL": "http://minio.invalid",
                "AWS_REGION": "ap-southeast-1",
                "REDIS_URL": "redis://staging.invalid/0",
                "REDIS_QUEUE": "patient-jobs",
            }
        )
        self.assertEqual(settings.postgres_dsn, "postgresql://staging.invalid/patient")
        self.assertEqual(settings.s3_bucket, "patient-staging")
        self.assertEqual(settings.redis_queue, "patient-jobs")


class S3ObjectStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = _FakeS3()
        self.store = S3ObjectStore("patient-staging", client=self.client, prefix="uploads")

    def test_health_put_get_and_same_content_retry(self) -> None:
        self.assertTrue(self.store.is_ready())
        self.assertEqual(self.store.put("doc-1", b"synthetic", media_type="application/pdf"), "doc-1")
        self.assertEqual(self.store.put("doc-1", b"synthetic", media_type="application/pdf"), "doc-1")
        self.assertEqual(self.store.get("doc-1"), b"synthetic")

    def test_same_key_with_changed_content_is_rejected(self) -> None:
        self.store.put("doc-2", b"first", media_type="application/pdf")
        with self.assertRaises(IdempotencyConflictError):
            self.store.put("doc-2", b"second", media_type="application/pdf")

    def test_missing_sdk_or_disabled_store_fails_closed(self) -> None:
        disabled = S3ObjectStore("patient-staging", client=self.client, available=False)
        self.assertFalse(disabled.is_ready())
        with self.assertRaises(DependencyUnavailableError):
            disabled.get("doc-1")


class RedisJobQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = _FakeRedis()
        self.queue = RedisJobQueue("redis://staging.invalid/0", client=self.client, queue_name="patient-jobs")

    def test_health_metadata_only_enqueue_and_idempotent_retry(self) -> None:
        self.assertTrue(self.queue.is_ready())
        payload = {"document_id": "document-synthetic", "job_type": "ocr"}
        self.queue.enqueue("job-1", payload)
        self.queue.enqueue("job-1", payload)
        self.assertEqual(self.queue.entries, [("job-1", payload)])
        self.assertNotIn("content", self.client.values["patient-jobs:job:job-1"])

    def test_same_job_with_changed_payload_is_rejected(self) -> None:
        self.queue.enqueue("job-2", {"document_id": "doc", "job_type": "ocr"})
        with self.assertRaises(IdempotencyConflictError):
            self.queue.enqueue("job-2", {"document_id": "doc", "job_type": "extract_facts"})

    def test_disabled_queue_fails_closed(self) -> None:
        disabled = RedisJobQueue("redis://staging.invalid/0", client=self.client, available=False)
        self.assertFalse(disabled.is_ready())
        with self.assertRaises(DependencyUnavailableError):
            disabled.enqueue("job-3", {})


class PostgresAdapterTests(unittest.TestCase):
    def test_empty_dsn_rejected_before_driver_import(self) -> None:
        with self.assertRaises(ValueError):
            PostgresMetadataStore("")

    def test_missing_driver_is_reported_as_unavailable(self) -> None:
        # This test is only meaningful when neither optional driver is loaded.
        # A CI job with a real Postgres service should use the integration test
        # command below instead of depending on this branch.
        try:
            import psycopg  # type: ignore[import-not-found]  # noqa: F401
            self.skipTest("psycopg is installed; run the staging integration test")
        except ModuleNotFoundError:
            pass
        try:
            import psycopg2  # type: ignore[import-not-found]  # noqa: F401
            self.skipTest("psycopg2 is installed; run the staging integration test")
        except ModuleNotFoundError:
            pass
        with self.assertRaises(DependencyUnavailableError):
            PostgresMetadataStore("postgresql://staging.invalid/patient", apply_migrations=False)


if __name__ == "__main__":
    unittest.main()
