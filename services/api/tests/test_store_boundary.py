from __future__ import annotations

import unittest

from services.api.app import ApiHttpAdapter
from services.api.dependencies import InMemoryJobQueue, InMemoryObjectStore
from services.api.models import AuthContext, PrincipalRole, Scope
from services.api.service import ApiService
from services.api.store import InMemoryStore, MetadataStore


class MetadataBoundaryTests(unittest.TestCase):
    def test_in_memory_store_implements_provider_neutral_boundary(self) -> None:
        store = InMemoryStore()
        self.assertIsInstance(store, MetadataStore)
        service = ApiService(store=store)
        auth = AuthContext(
            "patient-1",
            roles=frozenset({PrincipalRole.PATIENT}),
            scopes=frozenset({Scope.VISITS_READ, Scope.VISITS_WRITE}),
            request_id="metadata-boundary",
        )
        topic = service.create_topic(auth, name="Synthetic topic", idempotency_key="metadata-topic-001")
        self.assertEqual(service.list_topics(auth)[0].id, topic.id)
        self.assertTrue(store.list_audit_events())

    def test_explicit_missing_dependencies_fail_closed(self) -> None:
        service = ApiService(store=None, object_store=None, job_queue=None)
        response = ApiHttpAdapter(service).handle("GET", "/readyz")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.body["code"], "DEPENDENCY_UNAVAILABLE")
        self.assertEqual(response.body["status"], "not_ready")
        self.assertEqual(response.body["checks"], {"metadata_store": False, "object_store": False, "job_queue": False})

    def test_unavailable_provider_fails_closed_without_claiming_ready(self) -> None:
        store = InMemoryStore(available=False)
        object_store = InMemoryObjectStore(available=False)
        job_queue = InMemoryJobQueue(available=False)
        service = ApiService(store=store, object_store=object_store, job_queue=job_queue)
        response = ApiHttpAdapter(service).handle("GET", "/readyz")
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.body["checks"]["metadata_store"])
        self.assertFalse(response.body["checks"]["object_store"])
        self.assertFalse(response.body["checks"]["job_queue"])

    def test_provider_readiness_exception_is_treated_as_unavailable(self) -> None:
        class BrokenProvider:
            def is_ready(self) -> bool:
                raise RuntimeError("synthetic provider failure")

        service = ApiService(store=BrokenProvider())
        readiness = service.readiness()
        self.assertEqual(readiness["status"], "not_ready")
        self.assertFalse(readiness["checks"]["metadata_store"])


if __name__ == "__main__":
    unittest.main()
