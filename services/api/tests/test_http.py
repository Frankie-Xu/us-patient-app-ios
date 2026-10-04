from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from services.api.app import ApiHttpAdapter
from services.api.models import AuthContext, JobType, PrincipalRole, Scope
from services.api.service import ApiService


class HttpAdapterTests(unittest.TestCase):
    """Equivalent HTTP integration tests for the optional FastAPI adapter.

    The local environment intentionally has no FastAPI/TestClient dependency, so
    tests exercise the same request/response adapter used by FastAPI directly.
    """

    def setUp(self) -> None:
        self.now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        self.service = ApiService(clock=lambda: self.now)
        self.http = ApiHttpAdapter(self.service)
        self.scopes = ",".join(scope.value for scope in (
            Scope.DOCUMENTS_READ,
            Scope.DOCUMENTS_WRITE,
            Scope.FACTS_READ,
            Scope.FACTS_WRITE,
            Scope.SHARES_CREATE,
            Scope.SHARES_REVOKE,
            Scope.AUDIT_READ,
        ))

    def bearer(self, scopes: str | None = None, subject: str = "patient-1", role: str = "patient") -> dict[str, str]:
        return {"Authorization": f"Bearer {subject}|{scopes if scopes is not None else self.scopes}|{role}", "X-Request-Id": "http-test"}

    def test_upload_processing_facts_review_share_and_revoke(self) -> None:
        document = self.http.handle(
            "POST",
            "/v1/documents",
            headers={**self.bearer(), "Idempotency-Key": "http-doc-001"},
            body={"filename": "synthetic-note.pdf", "media_type": "application/pdf", "size_bytes": 10, "sha256": "d" * 64},
        )
        self.assertEqual(document.status_code, 201)
        document_id = document.body["id"]

        queued = self.http.handle(
            "POST",
            f"/v1/documents/{document_id}/processing-jobs",
            headers={**self.bearer(), "Idempotency-Key": "http-job-001"},
            body={"job_type": JobType.OCR.value},
        )
        self.assertEqual(queued.status_code, 202)
        worker = AuthContext("worker", roles=frozenset({PrincipalRole.SERVICE}), request_id="worker-http")
        self.service.complete_processing(worker, queued.body["id"], success=True)

        fact = self.http.handle(
            "POST",
            "/v1/facts",
            headers={**self.bearer(), "Idempotency-Key": "http-fact-001"},
            body={
                "label": "visit_reason",
                "value": "Synthetic follow-up",
                "source_ref": f"{document_id}:page-1:region-1",
                "source_type": "ai_extraction",
                "confidence": 0.84,
                "document_id": document_id,
            },
        )
        self.assertEqual(fact.status_code, 201)
        reviewed = self.http.handle(
            "POST",
            f"/v1/facts/{fact.body['id']}/review",
            headers={**self.bearer(), "If-Match-Version": "1"},
            body={"review_status": "confirmed"},
        )
        self.assertEqual(reviewed.status_code, 200)
        self.assertEqual(reviewed.body["review_status"], "confirmed")

        ready_document = self.service.store.documents[document_id]
        share = self.http.handle(
            "POST",
            "/v1/shares",
            headers={**self.bearer(), "Idempotency-Key": "http-share-001"},
            body={
                "resource_type": "document",
                "resource_id": document_id,
                "resource_version": ready_document.version,
                "expires_at": (self.now + timedelta(hours=1)).isoformat(),
            },
        )
        self.assertEqual(share.status_code, 201)
        token = share.body["token"]
        public = self.http.handle("GET", f"/v1/shared/{token}")
        self.assertEqual(public.status_code, 200)
        revoked = self.http.handle(
            "POST",
            f"/v1/shares/{share.body['share']['id']}/revoke",
            headers=self.bearer(),
        )
        self.assertEqual(revoked.status_code, 200)
        self.assertEqual(self.http.handle("GET", f"/v1/shared/{token}").status_code, 410)

    def test_401_403_409_and_404_boundaries(self) -> None:
        no_auth = self.http.handle(
            "POST",
            "/v1/documents",
            headers={"Idempotency-Key": "http-error-001"},
            body={"filename": "synthetic.pdf", "media_type": "application/pdf", "size_bytes": 1, "sha256": "e" * 64},
        )
        self.assertEqual(no_auth.status_code, 401)

        no_write_scope = self.http.handle(
            "POST",
            "/v1/documents",
            headers={**self.bearer(scopes="documents:read"), "Idempotency-Key": "http-error-002"},
            body={"filename": "synthetic.pdf", "media_type": "application/pdf", "size_bytes": 1, "sha256": "e" * 64},
        )
        self.assertEqual(no_write_scope.status_code, 403)

        owned = self.http.handle(
            "POST",
            "/v1/documents",
            headers={**self.bearer(), "Idempotency-Key": "http-error-owned"},
            body={"filename": "owned.pdf", "media_type": "application/pdf", "size_bytes": 1, "sha256": "f" * 64},
        )
        self.assertEqual(owned.status_code, 201)
        other_owner = self.http.handle(
            "GET",
            f"/v1/documents/{owned.body['id']}",
            headers=self.bearer(subject="patient-2"),
        )
        self.assertEqual(other_owner.status_code, 403)

        body = {"filename": "synthetic.pdf", "media_type": "application/pdf", "size_bytes": 1, "sha256": "e" * 64}
        first = self.http.handle("POST", "/v1/documents", headers={**self.bearer(), "Idempotency-Key": "http-error-003"}, body=body)
        self.assertEqual(first.status_code, 201)
        conflict = self.http.handle(
            "POST",
            "/v1/documents",
            headers={**self.bearer(), "Idempotency-Key": "http-error-003"},
            body={**body, "filename": "different.pdf"},
        )
        self.assertEqual(conflict.status_code, 409)

        missing = self.http.handle("GET", "/v1/documents/does-not-exist", headers=self.bearer())
        self.assertEqual(missing.status_code, 404)
        invalid_share = self.http.handle("GET", "/v1/shared/no-such-token")
        self.assertEqual(invalid_share.status_code, 404)


if __name__ == "__main__":
    unittest.main()
