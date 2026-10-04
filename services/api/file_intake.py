"""Provider-neutral file intake validation for staging uploads.

The API stores metadata and object references; this module validates the bounded
binary receipt at the upload boundary so PDF/photo/multi-page inputs cannot be
silently accepted as a different type. Detection is dependency free and uses
container signatures only. Production deployments can replace the detector with
a reviewed parser without changing the service contract.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import PurePath
from typing import Iterable

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MIN_UPLOAD_BYTES = 1

_MEDIA_ALIASES = {
    "image/jpg": "image/jpeg",
    "application/x-pdf": "application/pdf",
}
_SUPPORTED_MEDIA_TYPES = frozenset(
    {
        "application/pdf",
        "application/octet-stream",
        "image/jpeg",
        "image/png",
        "image/heic",
        "image/heif",
    }
)
_EXTENSION_MEDIA_TYPES = {
    ".pdf": frozenset({"application/pdf"}),
    ".jpg": frozenset({"image/jpeg"}),
    ".jpeg": frozenset({"image/jpeg"}),
    ".png": frozenset({"image/png"}),
    ".heic": frozenset({"image/heic", "image/heif"}),
    ".heif": frozenset({"image/heic", "image/heif"}),
}

_PAGE_MARKER = re.compile(rb"/Type\s*/Page(?:[\s/]|$)")


class FileIntakeError(ValueError):
    """Raised when declared or received file metadata is not acceptable."""


class UploadTooLargeError(FileIntakeError):
    """Raised before retaining bytes that exceed the configured upload bound."""


@dataclass(frozen=True)
class FileMetadata:
    """Deterministic metadata derived from a bounded binary receipt."""

    media_type: str
    container: str
    size_bytes: int
    sha256: str
    page_count: int | None = None

    def __post_init__(self) -> None:
        if self.media_type not in _SUPPORTED_MEDIA_TYPES:
            raise FileIntakeError("unsupported media type")
        if self.size_bytes < MIN_UPLOAD_BYTES or self.size_bytes > MAX_UPLOAD_BYTES:
            raise FileIntakeError("file size is outside the supported range")
        if len(self.sha256) != 64 or any(char not in "0123456789abcdef" for char in self.sha256):
            raise FileIntakeError("file checksum is invalid")
        if self.page_count is not None and self.page_count < 1:
            raise FileIntakeError("page count must be positive")


def normalize_media_type(media_type: str) -> str:
    if not isinstance(media_type, str) or not media_type.strip():
        raise FileIntakeError("media type is required")
    normalized = media_type.split(";", 1)[0].strip().lower()
    normalized = _MEDIA_ALIASES.get(normalized, normalized)
    if normalized not in _SUPPORTED_MEDIA_TYPES:
        raise FileIntakeError("unsupported media type")
    return normalized


def validate_declared_metadata(
    *,
    filename: str,
    media_type: str,
    size_bytes: int,
    sha256: str,
    max_bytes: int = MAX_UPLOAD_BYTES,
) -> str:
    """Validate the metadata request before creating a document resource."""
    if not isinstance(filename, str) or not filename.strip():
        raise FileIntakeError("filename is required")
    if "/" in filename or "\\" in filename or filename in {".", ".."}:
        raise FileIntakeError("filename must be a basename")
    if not isinstance(size_bytes, int) or isinstance(size_bytes, bool):
        raise FileIntakeError("size_bytes must be an integer")
    if not MIN_UPLOAD_BYTES <= size_bytes <= max_bytes:
        raise UploadTooLargeError("file size is outside the supported range")
    normalized = normalize_media_type(media_type)
    if not isinstance(sha256, str) or len(sha256) != 64 or any(char not in "0123456789abcdefABCDEF" for char in sha256):
        raise FileIntakeError("file checksum is invalid")
    suffix = PurePath(filename).suffix.lower()
    expected_types = _EXTENSION_MEDIA_TYPES.get(suffix)
    if expected_types is not None and normalized not in expected_types:
        raise FileIntakeError("filename extension does not match media type")
    return normalized


def _container_for(content: bytes, media_type: str) -> tuple[str, int | None]:
    if media_type == "application/octet-stream":
        return "binary", None
    if media_type == "application/pdf":
        if not content.startswith(b"%PDF-"):
            raise FileIntakeError("PDF signature is invalid")
        # Count explicit page objects when present. A minimal PDF still
        # represents one page for deterministic metadata.
        page_count = max(1, len(_PAGE_MARKER.findall(content)))
        return "pdf", page_count
    if media_type == "image/jpeg":
        if not content.startswith(b"\xff\xd8") or not content.endswith(b"\xff\xd9"):
            raise FileIntakeError("JPEG signature is invalid")
        return "jpeg", 1
    if media_type == "image/png":
        if not content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise FileIntakeError("PNG signature is invalid")
        return "png", 1
    if media_type in {"image/heic", "image/heif"}:
        if len(content) < 12 or content[4:8] != b"ftyp":
            raise FileIntakeError("HEIC signature is invalid")
        return "heif", 1
    raise FileIntakeError("unsupported media type")


def inspect_bytes(
    content: bytes,
    *,
    media_type: str,
    expected_size: int | None = None,
    expected_sha256: str | None = None,
    max_bytes: int = MAX_UPLOAD_BYTES,
) -> FileMetadata:
    """Inspect a bounded receipt and return normalized metadata."""
    if not isinstance(content, (bytes, bytearray, memoryview)):
        raise FileIntakeError("binary content is required")
    data = bytes(content)
    if len(data) > max_bytes:
        raise UploadTooLargeError("file size exceeds the supported range")
    if not MIN_UPLOAD_BYTES <= len(data):
        raise FileIntakeError("file must contain at least one byte")
    if expected_size is not None and len(data) != expected_size:
        raise FileIntakeError("file size does not match declared metadata")
    normalized = normalize_media_type(media_type)
    digest = hashlib.sha256(data).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256.lower():
        raise FileIntakeError("file checksum does not match declared metadata")
    container, page_count = _container_for(data, normalized)
    return FileMetadata(normalized, container, len(data), digest, page_count)


def iter_bounded(chunks: Iterable[bytes], *, max_bytes: int = MAX_UPLOAD_BYTES) -> bytes:
    """Consume a sync stream while retaining at most max_bytes bytes."""
    collected = bytearray()
    for chunk in chunks:
        if not isinstance(chunk, (bytes, bytearray, memoryview)):
            raise FileIntakeError("binary stream yielded a non-binary chunk")
        collected.extend(bytes(chunk))
        if len(collected) > max_bytes:
            raise UploadTooLargeError("stream exceeds the supported range")
    if not collected:
        raise FileIntakeError("stream must contain at least one byte")
    return bytes(collected)


def inspect_stream(
    chunks: Iterable[bytes],
    *,
    media_type: str,
    expected_size: int | None = None,
    expected_sha256: str | None = None,
    max_bytes: int = MAX_UPLOAD_BYTES,
) -> FileMetadata:
    """Validate metadata for a bounded iterable without changing the API contract."""
    data = iter_bounded(chunks, max_bytes=max_bytes)
    return inspect_bytes(
        data,
        media_type=media_type,
        expected_size=expected_size,
        expected_sha256=expected_sha256,
        max_bytes=max_bytes,
    )
