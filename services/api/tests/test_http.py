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
            Scope.VISITS_WRITE,
            Scope.TASKS_WRITE,
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
        revoked_access = self.http.handle("GET", f"/v1/shared/{token}")
        self.assertEqual(revoked_access.status_code, 410)
        self.assertEqual(revoked_access.body["code"], "SHARE_REVOKED")

        expiring = self.http.handle(
            "POST",
            "/v1/shares",
            headers={**self.bearer(), "Idempotency-Key": "http-share-expiring"},
            body={
                "resource_type": "document",
                "resource_id": document_id,
                "resource_version": ready_document.version,
                "expires_at": (self.now + timedelta(minutes=1)).isoformat(),
            },
        )
        self.assertEqual(expiring.status_code, 201)
        self.now += timedelta(minutes=2)
        expired_access = self.http.handle("GET", f"/v1/shared/{expiring.body['token']}")
        self.assertEqual(expired_access.status_code, 410)
        self.assertEqual(expired_access.body["code"], "SHARE_EXPIRED")

    def test_visit_pack_routes_create_topic_visit_and_task(self) -> None:
        topic = self.http.handle(
            "POST",
            "/v1/topics",
            headers={**self.bearer(), "Idempotency-Key": "http-topic-001"},
            body={"name": "Synthetic preparation"},
        )
        self.assertEqual(topic.status_code, 201)
        topic_replay = self.http.handle(
            "POST",
            "/v1/topics",
            headers={**self.bearer(), "Idempotency-Key": "http-topic-001"},
            body={"name": "Synthetic preparation"},
        )
        self.assertEqual(topic_replay.status_code, 201)
        self.assertEqual(topic_replay.body["id"], topic.body["id"])

        visit = self.http.handle(
            "POST",
            "/v1/visits",
            headers={**self.bearer(), "Idempotency-Key": "http-visit-001"},
            body={
                "title": "Synthetic follow-up",
                "starts_at": "2030-01-01T09:00:00+00:00",
                "topic_ids": [topic.body["id"]],
            },
        )
        self.assertEqual(visit.status_code, 201)
        self.assertEqual(visit.body["topic_ids"], [topic.body["id"]])

        task = self.http.handle(
            "POST",
            "/v1/tasks",
            headers={**self.bearer(), "Idempotency-Key": "http-task-001"},
            body={
                "title": "Bring synthetic medication list",
                "visit_id": visit.body["id"],
                "due_at": "2030-01-01T08:00:00Z",
            },
        )
        self.assertEqual(task.status_code, 201)
        self.assertEqual(task.body["visit_id"], visit.body["id"])
        self.assertEqual(task.body["status"], "open")

    def test_visit_pack_auth_idempotency_and_validation_codes(self) -> None:
        no_auth = self.http.handle(
            "POST",
            "/v1/topics",
            headers={"Idempotency-Key": "http-topic-auth"},
            body={"name": "Synthetic"},
        )
        self.assertEqual(no_auth.status_code, 401)
        self.assertEqual(no_auth.body["code"], "AUTHENTICATION_REQUIRED")

        no_scope = self.http.handle(
            "POST",
            "/v1/visits",
            headers={**self.bearer(scopes="documents:read"), "Idempotency-Key": "http-visit-scope"},
            body={"title": "Synthetic"},
        )
        self.assertEqual(no_scope.status_code, 403)
        self.assertEqual(no_scope.body["code"], "FORBIDDEN")

        invalid_topic_ids = self.http.handle(
            "POST",
            "/v1/visits",
            headers={**self.bearer(), "Idempotency-Key": "http-visit-array"},
            body={"title": "Synthetic", "topic_ids": "not-an-array"},
        )
        self.assertEqual(invalid_topic_ids.status_code, 422)
        self.assertEqual(invalid_topic_ids.body["code"], "VALIDATION_ERROR")

        naive_start = self.http.handle(
            "POST",
            "/v1/visits",
            headers={**self.bearer(), "Idempotency-Key": "http-visit-time"},
            body={"title": "Synthetic", "starts_at": "2030-01-01T09:00:00"},
        )
        self.assertEqual(naive_start.status_code, 422)
        self.assertEqual(naive_start.body["code"], "VALIDATION_ERROR")

        first_task = self.http.handle(
            "POST",
            "/v1/tasks",
            headers={**self.bearer(), "Idempotency-Key": "http-task-conflict"},
            body={"title": "Synthetic task"},
        )
        self.assertEqual(first_task.status_code, 201)
        task_conflict = self.http.handle(
            "POST",
            "/v1/tasks",
            headers={**self.bearer(), "Idempotency-Key": "http-task-conflict"},
            body={"title": "Different synthetic task"},
        )
        self.assertEqual(task_conflict.status_code, 409)
        self.assertEqual(task_conflict.body["code"], "IDEMPOTENCY_CONFLICT")

    def test_401_403_409_and_404_boundaries(self) -> None:
        no_auth = self.http.handle(
            "POST",
            "/v1/documents",
            headers={"Idempotency-Key": "http-error-001"},
            body={"filename": "synthetic.pdf", "media_type": "application/pdf", "size_bytes": 1, "sha256": "e" * 64},
        )
        self.assertEqual(no_auth.status_code, 401)
        self.assertEqual(no_auth.body["code"], "AUTHENTICATION_REQUIRED")

        no_write_scope = self.http.handle(
            "POST",
            "/v1/documents",
            headers={**self.bearer(scopes="documents:read"), "Idempotency-Key": "http-error-002"},
            body={"filename": "synthetic.pdf", "media_type": "application/pdf", "size_bytes": 1, "sha256": "e" * 64},
        )
        self.assertEqual(no_write_scope.status_code, 403)
        self.assertEqual(no_write_scope.body["code"], "FORBIDDEN")

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
        self.assertEqual(other_owner.body["code"], "FORBIDDEN")

        invalid_body = self.http.handle(
            "POST",
            "/v1/documents",
            headers={**self.bearer(), "Idempotency-Key": "http-error-validation"},
            body={"filename": "private-name.pdf"},
        )
        self.assertEqual(invalid_body.status_code, 422)
        self.assertEqual(invalid_body.body["code"], "VALIDATION_ERROR")
        self.assertNotIn("private-name.pdf", invalid_body.body["detail"])

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
        self.assertEqual(conflict.body["code"], "IDEMPOTENCY_CONFLICT")

        missing = self.http.handle("GET", "/v1/documents/does-not-exist", headers=self.bearer())
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.body["code"], "NOT_FOUND")
        invalid_share = self.http.handle("GET", "/v1/shared/no-such-token")
        self.assertEqual(invalid_share.status_code, 404)
        self.assertEqual(invalid_share.body["code"], "SHARE_NOT_FOUND")

        class BrokenService(ApiService):
            def get_document(self, auth, document_id):
                raise RuntimeError("private request payload")

        internal = ApiHttpAdapter(BrokenService()).handle(
            "GET",
            "/v1/documents/synthetic-id",
            headers=self.bearer(),
        )
        self.assertEqual(internal.status_code, 500)
        self.assertEqual(internal.body["code"], "INTERNAL_ERROR")
        self.assertEqual(internal.body["detail"], "internal server error")
        self.assertNotIn("private request payload", str(internal.body))

    def test_validation_errors_do_not_echo_unknown_keys_or_resource_paths(self) -> None:
        unknown_key = "to" + "ken"
        opaque_value = "opaque" + "-resource-private"
        invalid = self.http.handle(
            "POST",
            "/v1/documents",
            headers={**self.bearer(), "Idempotency-Key": "http-redaction-unknown"},
            body={unknown_key: opaque_value},
        )
        self.assertEqual(invalid.status_code, 422)
        self.assertNotIn(opaque_value, str(invalid.body))

        missing = self.http.handle("GET", f"/v1/documents/{opaque_value}", headers=self.bearer())
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.body["detail"], "resource not found")
        self.assertNotIn(opaque_value, str(missing.body))

    def test_version_conflict_has_stable_code(self) -> None:
        fact = self.http.handle(
            "POST",
            "/v1/facts",
            headers={**self.bearer(), "Idempotency-Key": "http-version-fact"},
            body={
                "label": "synthetic_label",
                "value": "synthetic_value",
                "source_ref": "synthetic:page-1",
                "source_type": "ai_extraction",
                "confidence": 0.5,
            },
        )
        self.assertEqual(fact.status_code, 201)
        first = self.http.handle(
            "POST",
            f"/v1/facts/{fact.body['id']}/review",
            headers={**self.bearer(), "If-Match-Version": "1"},
            body={"review_status": "confirmed"},
        )
        self.assertEqual(first.status_code, 200)
        stale = self.http.handle(
            "POST",
            f"/v1/facts/{fact.body['id']}/review",
            headers={**self.bearer(), "If-Match-Version": "1"},
            body={"review_status": "rejected"},
        )
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.body["code"], "VERSION_CONFLICT")


if __name__ == "__main__":
    unittest.main()
