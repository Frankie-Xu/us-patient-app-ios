from __future__ import annotations

import hashlib
import unittest
from datetime import datetime, timedelta, timezone

from services.api.app import ApiHttpAdapter
from services.api.models import AuthContext, PrincipalRole, Scope
from services.api.service import ApiService


class PdfShareLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        self.service = ApiService(clock=lambda: self.now)
        self.http = ApiHttpAdapter(self.service)
        self.scopes = ",".join(
            scope.value
            for scope in (
                Scope.DOCUMENTS_READ,
                Scope.DOCUMENTS_WRITE,
                Scope.FACTS_READ,
                Scope.FACTS_WRITE,
                Scope.SHARES_CREATE,
                Scope.SHARES_REVOKE,
                Scope.AUDIT_READ,
            )
        )

    def bearer(self, subject: str = "patient-1") -> dict[str, str]:
        return {
            "Authorization": f"Bearer {subject}|{self.scopes}|patient",
            "X-Request-Id": "pdf-share-test",
        }

    def service_auth(self) -> AuthContext:
        return AuthContext(
            "worker",
            roles=frozenset({PrincipalRole.SERVICE}),
            scopes=frozenset(),
            request_id="pdf-share-worker",
        )

    def ready_document(self) -> dict[str, object]:
        content = b"synthetic-pdf-input"
        created = self.http.handle(
            "POST",
            "/v1/documents",
            headers={**self.bearer(), "Idempotency-Key": "pdf-doc-001"},
            body={
                "filename": "synthetic-record.pdf",
                "media_type": "application/pdf",
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            },
        )
        self.assertEqual(created.status_code, 201)
        document_id = created.body["id"]
        session = self.http.handle(
            "POST",
            f"/v1/documents/{document_id}/upload-sessions",
            headers={**self.bearer(), "Idempotency-Key": "pdf-upload-001"},
            body={},
        )
        self.assertEqual(session.status_code, 201)
        uploaded = self.http.handle(
            "PUT",
            f"/v1/upload-sessions/{session.body['id']}/content",
            headers={**self.bearer(), "Content-Type": "application/octet-stream"},
            body=content,
        )
        self.assertEqual(uploaded.status_code, 200)
        job = self.http.handle(
            "POST",
            f"/v1/documents/{document_id}/processing-jobs",
            headers={**self.bearer(), "Idempotency-Key": "pdf-job-001"},
            body={"job_type": "ocr"},
        )
        self.assertEqual(job.status_code, 202)
        self.service.complete_processing(
            self.service_auth(),
            job.body["id"],
            success=True,
        )
        document = self.http.handle(
            "GET",
            f"/v1/documents/{document_id}",
            headers=self.bearer(),
        )
        self.assertEqual(document.status_code, 200)
        self.assertEqual(document.body["status"], "ready")
        return document.body

    def create_fact(self, document_id: str, label: str, value: str, key: str) -> dict[str, object]:
        response = self.http.handle(
            "POST",
            "/v1/facts",
            headers={**self.bearer(), "Idempotency-Key": key},
            body={
                "label": label,
                "value": value,
                "source_ref": "synthetic:page-1",
                "source_type": "ai_extraction",
                "confidence": 0.9,
                "document_id": document_id,
            },
        )
        self.assertEqual(response.status_code, 201)
        return response.body

    def confirm_fact(self, fact_id: str) -> dict[str, object]:
        response = self.http.handle(
            "POST",
            f"/v1/facts/{fact_id}/review",
            headers={**self.bearer(), "If-Match-Version": "1"},
            body={"review_status": "confirmed"},
        )
        self.assertEqual(response.status_code, 200)
        return response.body

    def test_deterministic_pdf_requires_confirmed_facts_and_pins_version(self) -> None:
        document = self.ready_document()
        fact = self.create_fact(document["id"], "Synthetic marker", "confirmed value", "pdf-fact-001")
        blocked = self.http.handle(
            "POST",
            f"/v1/documents/{document['id']}/exports/pdf",
            headers=self.bearer(),
            body={"document_version": document["version"], "fact_ids": [fact["id"]]},
        )
        self.assertEqual(blocked.status_code, 422)
        self.assertEqual(blocked.body["code"], "UNREVIEWED_CONTENT")

        self.confirm_fact(fact["id"])
        body = {"document_version": document["version"], "fact_ids": [fact["id"]]}
        first = self.http.handle(
            "POST",
            f"/v1/documents/{document['id']}/exports/pdf",
            headers=self.bearer(),
            body=body,
        )
        second = self.http.handle(
            "POST",
            f"/v1/documents/{document['id']}/exports/pdf",
            headers=self.bearer(),
            body=body,
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.headers["Content-Type"], "application/pdf")
        self.assertTrue(first.body.startswith(b"%PDF-1.4"))
        self.assertEqual(first.body, second.body)
        self.assertEqual(first.headers["X-Document-Version"], str(document["version"]))

        stale = self.http.handle(
            "GET",
            f"/v1/documents/{document['id']}/exports/pdf?version=1",
            headers=self.bearer(),
        )
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.body["code"], "DOCUMENT_VERSION_MISMATCH")

    def test_conflicted_content_fails_closed(self) -> None:
        document = self.ready_document()
        first = self.create_fact(document["id"], "Synthetic marker", "value one", "pdf-fact-002")
        second = self.create_fact(document["id"], "Synthetic marker", "value two", "pdf-fact-003")
        self.confirm_fact(first["id"])
        self.confirm_fact(second["id"])
        blocked = self.http.handle(
            "POST",
            f"/v1/documents/{document['id']}/exports/pdf",
            headers=self.bearer(),
            body={"document_version": document["version"]},
        )
        self.assertEqual(blocked.status_code, 422)
        self.assertEqual(blocked.body["code"], "CONFLICTED_CONTENT")

    def test_share_status_pdf_access_revoke_and_audit_are_controlled(self) -> None:
        document = self.ready_document()
        fact = self.create_fact(document["id"], "Synthetic marker", "share value", "pdf-fact-004")
        self.confirm_fact(fact["id"])
        share = self.http.handle(
            "POST",
            "/v1/shares",
            headers={**self.bearer(), "Idempotency-Key": "pdf-share-001"},
            body={
                "resource_type": "document",
                "resource_id": document["id"],
                "resource_version": document["version"],
                "expires_at": (self.now + timedelta(minutes=5)).isoformat(),
            },
        )
        self.assertEqual(share.status_code, 201)
        self.assertNotIn("token_digest", share.body["share"])
        status = self.http.handle(
            "GET",
            f"/v1/shares/{share.body['share']['id']}",
            headers=self.bearer(),
        )
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.body["status"], "active")
        pdf = self.http.handle("GET", f"/v1/shared/{share.body['token']}/pdf")
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.body.startswith(b"%PDF-1.4"))

        self.now += timedelta(minutes=6)
        expired = self.http.handle(
            "GET",
            f"/v1/shares/{share.body['share']['id']}",
            headers=self.bearer(),
        )
        self.assertEqual(expired.status_code, 200)
        self.assertEqual(expired.body["status"], "expired")

        revoked_share = self.http.handle(
            "POST",
            "/v1/shares",
            headers={**self.bearer(), "Idempotency-Key": "pdf-share-002"},
            body={
                "resource_type": "document",
                "resource_id": document["id"],
                "resource_version": document["version"],
                "expires_at": (self.now + timedelta(minutes=5)).isoformat(),
            },
        )
        self.assertEqual(revoked_share.status_code, 201)
        share_id = revoked_share.body["share"]["id"]
        revoke = self.http.handle(
            "POST",
            f"/v1/shares/{share_id}/revoke",
            headers=self.bearer(),
        )
        replay = self.http.handle(
            "POST",
            f"/v1/shares/{share_id}/revoke",
            headers=self.bearer(),
        )
        self.assertEqual(revoke.status_code, 200)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.body["status"], "revoked")
        audit = self.http.handle(
            "GET",
            f"/v1/audit-events?resource_id={share_id}",
            headers=self.bearer(),
        )
        self.assertEqual(audit.status_code, 200)
        self.assertEqual(
            len([event for event in audit.body if event["action"] == "share.revoked"]),
            1,
        )
        denied = self.http.handle("GET", f"/v1/shared/{revoked_share.body['token']}")
        self.assertEqual(denied.status_code, 410)
        self.assertEqual(denied.body["code"], "SHARE_REVOKED")
        self.assertNotIn("token_digest", str(denied.body))


if __name__ == "__main__":
    unittest.main()
