from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
import unittest
from datetime import datetime, timedelta, timezone

from services.api.app import ApiHttpAdapter
from services.api.dependencies import InMemoryObjectStore
from services.api.models import AuthContext, PrincipalRole, Scope
from services.api.service import ApiService, UploadSessionError


class UploadSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        self.store = InMemoryObjectStore()
        self.service = ApiService(clock=lambda: self.now, object_store=self.store)
        scopes = frozenset({Scope.DOCUMENTS_READ, Scope.DOCUMENTS_WRITE})
        self.auth = AuthContext("patient-1", roles=frozenset({PrincipalRole.PATIENT}), scopes=scopes, request_id="upload-test")
        self.http = ApiHttpAdapter(self.service)

    def _document(self, content: bytes = b"synthetic-upload"):
        return self.service.create_document(
            self.auth,
            filename="synthetic.bin",
            media_type="application/octet-stream",
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            idempotency_key="document-upload-001",
        )

    def test_http_session_verifies_size_checksum_and_replays(self) -> None:
        content = b"synthetic-upload"
        document = self._document(content)
        headers = {"Authorization": "Bearer patient-1|documents:write|patient", "Idempotency-Key": "session-upload-001"}
        created = self.http.handle("POST", f"/v1/documents/{document.id}/upload-sessions", headers=headers, body={})
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.body["status"], "pending")
        session_id = created.body["id"]
        replay = self.http.handle("POST", f"/v1/documents/{document.id}/upload-sessions", headers=headers, body={})
        self.assertEqual(replay.status_code, 201)
        self.assertEqual(replay.body["id"], session_id)

        missing_type = self.http.handle("PUT", f"/v1/upload-sessions/{session_id}/content", headers={**headers, "Content-Type": "text/plain"}, body=content)
        self.assertEqual(missing_type.status_code, 422)
        uploaded = self.http.handle("PUT", f"/v1/upload-sessions/{session_id}/content", headers={**headers, "Content-Type": "application/octet-stream"}, body=content)
        self.assertEqual(uploaded.status_code, 200)
        self.assertEqual(uploaded.body["status"], "verified")
        self.assertNotIn("object_key", uploaded.body)
        self.assertEqual(self.store.get(f"uploads/{session_id}"), content)
        again = self.http.handle("PUT", f"/v1/upload-sessions/{session_id}/content", headers={**headers, "Content-Type": "application/octet-stream"}, body=content)
        self.assertEqual(again.status_code, 200)
        self.assertEqual(len([e for e in self.service.store.audit_events if e.action == "upload_session.verified"]), 1)

    def test_checksum_mismatch_and_expiry_are_stable(self) -> None:
        content = b"synthetic-upload"
        document = self._document(content)
        headers = {"Authorization": "Bearer patient-1|documents:write|patient", "Idempotency-Key": "session-upload-002"}
        created = self.http.handle("POST", f"/v1/documents/{document.id}/upload-sessions", headers=headers, body={})
        session_id = created.body["id"]
        bad = self.http.handle("PUT", f"/v1/upload-sessions/{session_id}/content", headers={**headers, "Content-Type": "application/octet-stream"}, body=b"wrong")
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(bad.body["code"], "UPLOAD_INTEGRITY_MISMATCH")
        self.now += timedelta(minutes=16)
        expired = self.http.handle("PUT", f"/v1/upload-sessions/{session_id}/content", headers={**headers, "Content-Type": "application/octet-stream"}, body=content)
        self.assertEqual(expired.status_code, 410)
        self.assertEqual(expired.body["code"], "UPLOAD_EXPIRED")
        self.assertEqual(self.store._objects, {})

    def test_owner_and_storage_boundaries_do_not_leak_content(self) -> None:
        content = b"synthetic-upload"
        document = self._document(content)
        created = self.service.create_upload_session(self.auth, document_id=document.id, idempotency_key="session-upload-003")
        other = AuthContext("patient-2", roles=frozenset({PrincipalRole.PATIENT}), scopes=frozenset({Scope.DOCUMENTS_WRITE}), request_id="other-upload")
        with self.assertRaises(Exception) as denied:
            self.service.upload_content(other, created.id, content)
        self.assertNotIn("synthetic-upload", str(denied.exception))
        self.store.available = False
        with self.assertRaises(UploadSessionError) as unavailable:
            self.service.upload_content(self.auth, created.id, content)
        self.assertEqual(unavailable.exception.status_code, 503)
        self.assertEqual(self.service.store.upload_sessions[created.id].status.value, "pending")

    def test_size_cap_is_enforced_at_session_creation(self) -> None:
        oversized = self.service.create_document(self.auth, filename="large.bin", media_type="application/octet-stream", size_bytes=10 * 1024 * 1024 + 1, sha256="a" * 64, idempotency_key="document-upload-large")
        with self.assertRaises(UploadSessionError) as error:
            self.service.create_upload_session(self.auth, document_id=oversized.id, idempotency_key="session-upload-large")
        self.assertEqual(error.exception.status_code, 413)

    def test_same_account_checksum_deduplicates_across_new_idempotency_keys(self) -> None:
        content = b"same-account-checksum"
        checksum = hashlib.sha256(content).hexdigest()
        first = self.service.create_document(
            self.auth,
            filename="original.bin",
            media_type="application/octet-stream",
            size_bytes=len(content),
            sha256=checksum,
            idempotency_key="document-dedupe-001",
        )
        duplicate = self.service.create_document(
            self.auth,
            filename="renamed.pdf",
            media_type="application/pdf",
            size_bytes=len(content),
            sha256=checksum.upper(),
            idempotency_key="document-dedupe-002",
        )
        self.assertEqual(duplicate.id, first.id)
        self.assertEqual(len(self.service.store.documents), 1)
        self.assertEqual(self.service.store.idempotency[(self.auth.subject_id, "document-dedupe-002")].response_status, 201)
        self.assertEqual(
            [event.action for event in self.service.store.audit_events],
            ["document.created", "document.deduplicated"],
        )

        # The new key is now an ordinary replay and does not append a second
        # audit event or create another resource.
        replay = self.service.create_document(
            self.auth,
            filename="renamed.pdf",
            media_type="application/pdf",
            size_bytes=len(content),
            sha256=checksum.upper(),
            idempotency_key="document-dedupe-002",
        )
        self.assertEqual(replay.id, first.id)
        self.assertEqual(len(self.service.store.audit_events), 2)

    def test_checksum_deduplication_is_account_scoped_and_size_bounded(self) -> None:
        content = b"account-boundary"
        checksum = hashlib.sha256(content).hexdigest()
        first = self.service.create_document(
            self.auth,
            filename="patient-one.bin",
            media_type="application/octet-stream",
            size_bytes=len(content),
            sha256=checksum,
            idempotency_key="document-boundary-001",
        )
        other = AuthContext(
            "patient-2",
            roles=frozenset({PrincipalRole.PATIENT}),
            scopes=frozenset({Scope.DOCUMENTS_WRITE}),
            request_id="other-upload",
        )
        other_account = self.service.create_document(
            other,
            filename="patient-two.bin",
            media_type="application/octet-stream",
            size_bytes=len(content),
            sha256=checksum,
            idempotency_key="document-boundary-002",
        )
        self.assertNotEqual(other_account.id, first.id)

        # A checksum match with inconsistent metadata size is not treated as
        # the same content receipt, even though SHA-256 values are supplied by
        # the caller and the model permits synthetic boundary fixtures.
        different_size = self.service.create_document(
            self.auth,
            filename="different-size.bin",
            media_type="application/octet-stream",
            size_bytes=len(content) + 1,
            sha256=checksum,
            idempotency_key="document-boundary-003",
        )
        self.assertNotEqual(different_size.id, first.id)
        self.assertEqual(len(self.service.store.documents), 3)

    def test_concurrent_new_keys_share_one_checksum_receipt(self) -> None:
        content = b"concurrent-dedupe"
        checksum = hashlib.sha256(content).hexdigest()

        def submit(index: int) -> str:
            document = self.service.create_document(
                self.auth,
                filename=f"concurrent-{index}.bin",
                media_type="application/octet-stream",
                size_bytes=len(content),
                sha256=checksum,
                idempotency_key=f"document-concurrent-{index}",
            )
            return document.id

        with ThreadPoolExecutor(max_workers=8) as executor:
            ids = list(executor.map(submit, range(24)))

        self.assertEqual(set(ids), {ids[0]})
        self.assertEqual(len(self.service.store.documents), 1)
        self.assertEqual(
            len([event for event in self.service.store.audit_events if event.action == "document.created"]),
            1,
        )
        self.assertEqual(
            len([event for event in self.service.store.audit_events if event.action == "document.deduplicated"]),
            23,
        )


if __name__ == "__main__":
    unittest.main()
