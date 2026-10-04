"""S3-compatible object-store adapter seam.

The adapter accepts an injected S3 client instead of importing boto3. This
keeps dependency installation and credentials in the staging deployment layer.
The client must implement put_object, get_object and optionally head_bucket.
Raw bytes are bounded and never logged.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ..dependencies import DependencyUnavailableError


class S3Client(Protocol):
    def put_object(self, **kwargs: Any) -> Any:
        ...

    def get_object(self, **kwargs: Any) -> Any:
        ...


@dataclass(frozen=True)
class S3ObjectStoreConfig:
    bucket: str
    region: str
    endpoint_url: str | None = None
    key_prefix: str = "patient-app"
    max_bytes: int = 10 * 1024 * 1024

    def __post_init__(self) -> None:
        if not self.bucket.strip() or not self.region.strip():
            raise ValueError("S3 bucket and region are required")
        if self.max_bytes < 1:
            raise ValueError("S3 max_bytes must be positive")
        if self.key_prefix.startswith("/"):
            raise ValueError("S3 key_prefix must be relative")


class S3ObjectStore:
    """ObjectStore-compatible adapter for AWS S3 or an S3-compatible service."""

    def __init__(self, client: S3Client, config: S3ObjectStoreConfig, *, available: bool = True) -> None:
        self.client = client
        self.config = config
        self.available = available

    def is_ready(self) -> bool:
        return self.available

    def _require_available(self) -> None:
        if not self.available:
            raise DependencyUnavailableError("object store is unavailable")

    def _key(self, key: str) -> str:
        self._require_available()
        if not isinstance(key, str) or not key.strip() or key.startswith("/"):
            raise ValueError("object-store key is required and must be relative")
        prefix = self.config.key_prefix.strip("/")
        return f"{prefix}/{key}" if prefix else key

    def put(self, key: str, content: bytes, *, media_type: str) -> str:
        object_key = self._key(key)
        if not isinstance(content, bytes):
            raise TypeError("object-store content must be bytes")
        if not 1 <= len(content) <= self.config.max_bytes:
            raise ValueError("object-store content exceeds configured bounds")
        try:
            self.client.put_object(
                Bucket=self.config.bucket,
                Key=object_key,
                Body=content,
                ContentLength=len(content),
                ContentType=media_type,
            )
        except Exception as exc:
            raise DependencyUnavailableError("object store write failed") from exc
        return object_key

    def get(self, key: str) -> bytes:
        object_key = self._key(key)
        try:
            response = self.client.get_object(Bucket=self.config.bucket, Key=object_key)
            body = response["Body"]
            content = body.read() if hasattr(body, "read") else body
        except Exception as exc:
            raise DependencyUnavailableError("object store read failed") from exc
        if not isinstance(content, bytes) or not 1 <= len(content) <= self.config.max_bytes:
            raise ValueError("object-store response exceeds configured bounds")
        return content
