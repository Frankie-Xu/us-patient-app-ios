from __future__ import annotations

import unittest
from datetime import datetime, timezone

from services.api.app import ApiHttpAdapter
from services.api.dependencies import DependencyUnavailableError, InMemoryJobQueue, InMemoryObjectStore
from services.api.models import AuthContext, JobType, PrincipalRole, Scope
from services.api.service import ApiService


class DependencyBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.object_store = InMemoryObjectStore()
        self.job_queue = InMemoryJobQueue()
        self.service = ApiService(
            clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
            object_store=self.object_store,
            job_queue=self.job_queue,
        )
        self.http = ApiHttpAdapter(self.service)
        self.auth = AuthContext(
            "patient-1",
            roles=frozenset({PrincipalRole.PATIENT}),
            scopes=frozenset({Scope.DOCUMENTS_WRITE, Scope.DOCUMENTS_READ}),
            request_id="dependency-test",
        )

    def test_health_and_readiness_reflect_dependency_availability(self) -> None:
        self.assertEqual(self.http.handle("GET", "/healthz").status_code, 200)
        ready = self.http.handle("GET", "/readyz")
        self.assertEqual(ready.status_code, 200)
        self.assertEqual(ready.body["status"], "ready")
        self.assertEqual(ready.body["checks"], {"metadata_store": True, "object_store": True, "job_queue": True})

        self.object_store.available = False
        not_ready = self.http.handle("GET", "/readyz")
        self.assertEqual(not_ready.status_code, 503)
        self.assertEqual(not_ready.body["code"], "DEPENDENCY_UNAVAILABLE")
        self.assertEqual(not_ready.body["status"], "not_ready")
        self.assertFalse(not_ready.body["checks"]["object_store"])

        self.object_store.available = True
        self.job_queue.available = False
        not_ready = self.http.handle("GET", "/readyz")
        self.assertEqual(not_ready.status_code, 503)
        self.assertEqual(not_ready.body["code"], "DEPENDENCY_UNAVAILABLE")
        self.assertFalse(not_ready.body["checks"]["job_queue"])

        document = self.service.create_document(
            self.auth,
            filename="synthetic.pdf",
            media_type="application/pdf",
            size_bytes=1,
            sha256="b" * 64,
            idempotency_key="dependency-http-doc",
        )
        queued = self.http.handle(
            "POST",
            f"/v1/documents/{document.id}/processing-jobs",
            headers={"Authorization": "Bearer patient-1|documents:write|patient", "Idempotency-Key": "dependency-http-job"},
            body={"job_type": "ocr"},
        )
        self.assertEqual(queued.status_code, 503)
        self.assertEqual(queued.body["code"], "DEPENDENCY_UNAVAILABLE")

    def test_job_queue_is_injected_and_unavailable_queue_does_not_mutate_state(self) -> None:
        document = self.service.create_document(
            self.auth,
            filename="synthetic.pdf",
            media_type="application/pdf",
            size_bytes=1,
            sha256="a" * 64,
            idempotency_key="dependency-doc-001",
        )
        self.job_queue.available = False
        with self.assertRaises(DependencyUnavailableError):
            self.service.enqueue_processing(
                self.auth,
                document_id=document.id,
                job_type=JobType.OCR,
                idempotency_key="dependency-job-001",
            )
        self.assertEqual(self.service.store.documents[document.id].status.value, "uploaded")
        self.assertEqual(self.service.store.jobs, {})
        self.assertEqual(self.job_queue.entries, [])

        self.job_queue.available = True
        job = self.service.enqueue_processing(
            self.auth,
            document_id=document.id,
            job_type=JobType.OCR,
            idempotency_key="dependency-job-002",
        )
        self.assertEqual(self.job_queue.entries, [(job.id, {"document_id": document.id, "job_type": "ocr"})])

    def test_object_store_double_is_replaceable_without_logging_payload(self) -> None:
        self.assertEqual(self.object_store.put("synthetic-key", b"synthetic-bytes", media_type="application/pdf"), "synthetic-key")
        self.assertEqual(self.object_store.get("synthetic-key"), b"synthetic-bytes")
        self.object_store.available = False
        with self.assertRaises(DependencyUnavailableError):
            self.object_store.get("synthetic-key")


if __name__ == "__main__":
    unittest.main()
