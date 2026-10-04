from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.api.dependencies import DependencyUnavailableError, SQLiteJobQueue, SQLiteObjectStore
from services.api.models import AuthContext, PrincipalRole, Scope
from services.api.service import ApiService
from services.api.store import SQLiteMetadataStore, VersionConflictError


class DurableAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.metadata_path = root / "metadata.sqlite3"
        self.object_path = root / "objects.sqlite3"
        self.queue_path = root / "queue.sqlite3"
        self.auth = AuthContext(
            "synthetic-patient",
            roles=frozenset({PrincipalRole.PATIENT}),
            scopes=frozenset({Scope.DOCUMENTS_READ, Scope.DOCUMENTS_WRITE}),
            request_id="durable-adapter-test",
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_metadata_and_idempotency_survive_reopen(self) -> None:
        first = SQLiteMetadataStore(self.metadata_path)
        service = ApiService(store=first)
        document = service.create_document(
            self.auth,
            filename="synthetic-record.pdf",
            media_type="application/pdf",
            size_bytes=1,
            sha256=hashlib.sha256(b"x").hexdigest(),
            idempotency_key="synthetic-create-001",
        )
        first.close()

        second = SQLiteMetadataStore(self.metadata_path)
        replay_service = ApiService(store=second)
        replay = replay_service.create_document(
            self.auth,
            filename="synthetic-record.pdf",
            media_type="application/pdf",
            size_bytes=1,
            sha256=hashlib.sha256(b"x").hexdigest(),
            idempotency_key="synthetic-create-001",
        )
        self.assertEqual(replay.id, document.id)
        self.assertEqual(second.get_resource("documents", document.id).filename, "synthetic-record.pdf")
        self.assertEqual(len(second.list_audit_events()), 1)
        second.close()

    def test_optimistic_version_conflict_survives_durable_boundary(self) -> None:
        store = SQLiteMetadataStore(self.metadata_path)
        service = ApiService(store=store)
        document = service.create_document(
            self.auth,
            filename="synthetic-record.pdf",
            media_type="application/pdf",
            size_bytes=1,
            sha256=hashlib.sha256(b"y").hexdigest(),
            idempotency_key="synthetic-create-002",
        )
        with self.assertRaises(VersionConflictError):
            store.save_resource("documents", document, expected_version=document.version)
        store.close()

    def test_object_bytes_and_queue_metadata_survive_reopen(self) -> None:
        object_store = SQLiteObjectStore(self.object_path)
        queue = SQLiteJobQueue(self.queue_path)
        object_store.put("uploads/synthetic-001", b"synthetic-bytes", media_type="application/pdf")
        queue.enqueue("job-synthetic-001", {"document_id": "document-synthetic-001", "job_type": "ocr"})
        object_store.close()
        queue.close()

        reopened_objects = SQLiteObjectStore(self.object_path)
        reopened_queue = SQLiteJobQueue(self.queue_path)
        self.assertEqual(reopened_objects.get("uploads/synthetic-001"), b"synthetic-bytes")
        self.assertEqual(reopened_queue.entries, [("job-synthetic-001", {"document_id": "document-synthetic-001", "job_type": "ocr"})])
        reopened_objects.close()
        reopened_queue.close()

    def test_durable_adapters_reject_future_schema_version(self) -> None:
        adapters = (
            (self.metadata_path, SQLiteMetadataStore),
            (self.object_path, SQLiteObjectStore),
            (self.queue_path, SQLiteJobQueue),
        )
        for path, adapter_type in adapters:
            adapter = adapter_type(path)
            adapter.close()
            connection = sqlite3.connect(path)
            connection.execute("PRAGMA user_version = 99")
            connection.commit()
            connection.close()
            with self.assertRaises(DependencyUnavailableError):
                adapter_type(path)

    def test_durable_adapters_fail_closed_when_disabled(self) -> None:
        store = SQLiteMetadataStore(self.metadata_path, available=False)
        object_store = SQLiteObjectStore(self.object_path, available=False)
        queue = SQLiteJobQueue(self.queue_path, available=False)
        self.assertFalse(store.is_ready())
        self.assertFalse(object_store.is_ready())
        self.assertFalse(queue.is_ready())
        with self.assertRaisesRegex(Exception, "unavailable"):
            store.list_resources("documents")
        store.close()
        object_store.close()
        queue.close()


if __name__ == "__main__":
    unittest.main()
