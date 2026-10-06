from __future__ import annotations

import hashlib

import pytest

from services.api.file_intake import (
    FileIntakeError,
    UploadTooLargeError,
    inspect_bytes,
    inspect_stream,
    validate_declared_metadata,
)
from services.api.models import AuthContext, PrincipalRole, Scope
from services.api.service import ApiService, UploadSessionError


def _auth() -> AuthContext:
    return AuthContext(
        "synthetic-owner",
        roles=frozenset({PrincipalRole.PATIENT}),
        scopes=frozenset({Scope.DOCUMENTS_READ, Scope.DOCUMENTS_WRITE}),
        request_id="file-intake-test",
    )


def test_pdf_and_multipage_metadata_is_deterministic() -> None:
    content = b"%PDF-1.7\n1 0 obj << /Type /Page >> endobj\n2 0 obj << /Type /Page >> endobj\n%%EOF"
    result = inspect_bytes(
        content,
        media_type="application/pdf",
        expected_size=len(content),
        expected_sha256=hashlib.sha256(content).hexdigest(),
    )
    assert result.container == "pdf"
    assert result.page_count == 2
    assert result.sha256 == hashlib.sha256(content).hexdigest()


@pytest.mark.parametrize(
    ("media_type", "content"),
    [
        ("image/jpeg", b"\xff\xd8synthetic\xff\xd9"),
        ("image/png", b"\x89PNG\r\n\x1a\nsynthetic"),
        ("image/heic", b"\x00\x00\x00\x18ftypheicsynthetic"),
        ("application/octet-stream", b"synthetic-binary"),
    ],
)
def test_photo_and_opaque_binary_signatures(media_type: str, content: bytes) -> None:
    result = inspect_bytes(content, media_type=media_type)
    assert result.media_type == media_type


def test_declared_metadata_rejects_extension_mismatch_and_stream_overflow() -> None:
    with pytest.raises(FileIntakeError):
        validate_declared_metadata(
            filename="synthetic.pdf",
            media_type="image/png",
            size_bytes=8,
            sha256="a" * 64,
        )
    with pytest.raises(UploadTooLargeError):
        inspect_stream([b"a" * 4, b"b" * 4], media_type="application/octet-stream", max_bytes=7)


def test_service_detects_same_content_for_owner_and_replays_new_key() -> None:
    service = ApiService()
    auth = _auth()
    content = b"synthetic-binary"
    digest = hashlib.sha256(content).hexdigest()
    first = service.create_document(
        auth,
        filename="synthetic.bin",
        media_type="application/octet-stream",
        size_bytes=len(content),
        sha256=digest,
        idempotency_key="doc-intake-1",
    )
    duplicate = service.create_document(
        auth,
        filename="renamed.bin",
        media_type="application/octet-stream",
        size_bytes=len(content),
        sha256=digest,
        idempotency_key="doc-intake-2",
    )
    assert duplicate.id == first.id
    assert any(event.action == "document.duplicate_detected" for event in service.store.audit_events)


def test_service_rejects_invalid_pdf_receipt_before_object_store_write() -> None:
    service = ApiService()
    auth = _auth()
    content = b"not-a-pdf"
    document = service.create_document(
        auth,
        filename="synthetic.pdf",
        media_type="application/pdf",
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        idempotency_key="doc-intake-pdf",
    )
    session = service.create_upload_session(auth, document_id=document.id, idempotency_key="session-intake-pdf")
    with pytest.raises(UploadSessionError) as error:
        service.upload_content(auth, session.id, content)
    assert error.value.code == "UPLOAD_FORMAT_INVALID"
    assert service.object_store._objects == {}
