from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from services.api.auth import AuthorizationError
from services.api.models import (
    AuthContext,
    JobType,
    PrincipalRole,
    ReviewStatus,
    Scope,
    ShareStatus,
    SourceType,
)
from services.api.service import ApiService, ShareAccessError
from services.api.store import IdempotencyConflictError, VersionConflictError


class ApiServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        self.service = ApiService(clock=lambda: self.now)
        self.auth = AuthContext(
            "patient-1",
            roles=frozenset({PrincipalRole.PATIENT}),
            scopes=frozenset({
                Scope.DOCUMENTS_READ,
                Scope.DOCUMENTS_WRITE,
                Scope.FACTS_READ,
                Scope.FACTS_WRITE,
                Scope.VISITS_WRITE,
                Scope.TASKS_WRITE,
                Scope.SHARES_CREATE,
                Scope.SHARES_REVOKE,
                Scope.AUDIT_READ,
            }),
            request_id="req-1",
        )

    def test_document_idempotency_replays_same_resource(self) -> None:
        kwargs = dict(filename="synthetic-lab.pdf", media_type="application/pdf", size_bytes=12, sha256="a" * 64, idempotency_key="doc-key-001")
        first = self.service.create_document(self.auth, **kwargs)
        replay = self.service.create_document(self.auth, **kwargs)
        self.assertEqual(first.id, replay.id)
        self.assertEqual(len(self.service.store.documents), 1)
        with self.assertRaises(IdempotencyConflictError):
            self.service.create_document(self.auth, **{**kwargs, "filename": "different.pdf"})

    def test_fact_keeps_source_confidence_and_requires_explicit_review(self) -> None:
        fact = self.service.create_fact(
            self.auth,
            label="medication",
            value="Synthetic Example",
            source_ref="doc-1:p1:r1",
            source_type=SourceType.AI_EXTRACTION,
            confidence=0.72,
            idempotency_key="fact-key-001",
        )
        self.assertEqual(fact.review_status, ReviewStatus.UNREVIEWED)
        self.assertEqual(fact.source_ref, "doc-1:p1:r1")
        self.assertEqual(fact.confidence, 0.72)
        reviewed = self.service.review_fact(self.auth, fact.id, review_status=ReviewStatus.CONFIRMED, expected_version=1)
        self.assertEqual(reviewed.review_status, ReviewStatus.CONFIRMED)
        self.assertEqual(reviewed.version, 2)
        with self.assertRaises(VersionConflictError):
            self.service.review_fact(self.auth, fact.id, review_status=ReviewStatus.REJECTED, expected_version=1)

    def test_upload_processing_is_audited_and_service_completion_is_role_bound(self) -> None:
        document = self.service.create_document(self.auth, filename="synthetic.pdf", media_type="application/pdf", size_bytes=1, sha256="b" * 64, idempotency_key="doc-key-002")
        job = self.service.enqueue_processing(self.auth, document_id=document.id, job_type=JobType.OCR, idempotency_key="job-key-001")
        self.assertEqual(job.status.value, "queued")
        with self.assertRaises(AuthorizationError):
            self.service.complete_processing(self.auth, job.id, success=True)
        worker = AuthContext("worker", roles=frozenset({PrincipalRole.SERVICE}), request_id="worker-req")
        completed = self.service.complete_processing(worker, job.id, success=True)
        self.assertEqual(completed.status.value, "succeeded")
        self.assertEqual(self.service.store.documents[document.id].status.value, "ready")

    def test_share_expiry_and_revoke_block_new_access(self) -> None:
        topic = self.service.create_topic(self.auth, name="Synthetic visit", idempotency_key="topic-key-001")
        share, token = self.service.create_share(
            self.auth,
            resource_type="topic",
            resource_id=topic.id,
            resource_version=topic.version,
            expires_at=self.now + timedelta(hours=1),
            idempotency_key="share-key-001",
        )
        self.assertEqual(share.status, ShareStatus.ACTIVE)
        accessed_share, resource = self.service.access_share(token)
        self.assertEqual(accessed_share.id, share.id)
        self.assertEqual(resource.id, topic.id)
        self.service.revoke_share(self.auth, share.id)
        with self.assertRaises(ShareAccessError):
            self.service.access_share(token)

        expiring_share, expiring_token = self.service.create_share(
            self.auth,
            resource_type="topic",
            resource_id=topic.id,
            resource_version=topic.version,
            expires_at=self.now + timedelta(minutes=5),
            idempotency_key="share-key-002",
        )
        self.now += timedelta(minutes=6)
        self.assertEqual(expiring_share.effective_status(self.now), ShareStatus.EXPIRED)
        with self.assertRaises(ShareAccessError):
            self.service.access_share(expiring_token)

    def test_upload_processing_facts_review_share_revoke_main_path(self) -> None:
        document = self.service.create_document(
            self.auth,
            filename="synthetic-visit-note.pdf",
            media_type="application/pdf",
            size_bytes=24,
            sha256="c" * 64,
            idempotency_key="path-doc-001",
        )
        queued = self.service.enqueue_processing(
            self.auth,
            document_id=document.id,
            job_type=JobType.OCR,
            idempotency_key="path-job-001",
        )
        worker = AuthContext("worker", roles=frozenset({PrincipalRole.SERVICE}), request_id="path-worker")
        completed = self.service.complete_processing(worker, queued.id, success=True)
        ready_document = self.service.store.documents[document.id]
        self.assertEqual(completed.status.value, "succeeded")
        self.assertEqual(ready_document.status.value, "ready")
        self.assertEqual(ready_document.version, 3)

        fact = self.service.create_fact(
            self.auth,
            label="visit_reason",
            value="Synthetic follow-up",
            source_ref=f"{document.id}:page-1:region-1",
            source_type=SourceType.AI_EXTRACTION,
            confidence=0.81,
            document_id=document.id,
            idempotency_key="path-fact-001",
        )
        reviewed = self.service.review_fact(
            self.auth,
            fact.id,
            review_status=ReviewStatus.CONFIRMED,
            expected_version=fact.version,
        )
        self.assertEqual(reviewed.review_status, ReviewStatus.CONFIRMED)

        share, token = self.service.create_share(
            self.auth,
            resource_type="document",
            resource_id=document.id,
            resource_version=ready_document.version,
            expires_at=self.now + timedelta(hours=1),
            idempotency_key="path-share-001",
        )
        accessed_share, accessed_document = self.service.access_share(token)
        self.assertEqual(accessed_share.resource_version, ready_document.version)
        self.assertEqual(accessed_document.id, document.id)
        self.service.revoke_share(self.auth, share.id)
        with self.assertRaises(ShareAccessError):
            self.service.access_share(token)

        actions = [event.action for event in self.service.store.audit_events]
        for action in (
            "document.created",
            "upload_processing.queued",
            "upload_processing.completed",
            "fact.created",
            "fact.reviewed",
            "share.created",
            "share.revoked",
        ):
            self.assertIn(action, actions)

    def test_audit_is_scalar_and_owner_scoped(self) -> None:
        self.service.create_topic(self.auth, name="Synthetic", idempotency_key="topic-key-002")
        events = self.service.list_audit(self.auth)
        self.assertTrue(events)
        for event in events:
            self.assertNotIn("value", event.metadata)
            self.assertNotIn("filename", event.metadata)
        other = AuthContext("other", scopes=frozenset({Scope.AUDIT_READ}), request_id="req-2")
        self.assertEqual(self.service.list_audit(other), [])


if __name__ == "__main__":
    unittest.main()
