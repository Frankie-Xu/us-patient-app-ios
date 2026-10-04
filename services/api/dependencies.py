"""Replaceable infrastructure boundaries for the local API skeleton.

These adapters deliberately keep payloads metadata-only. Production adapters may
back them with encrypted object storage and a durable queue, but the core service
never needs to know which provider is used.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol, runtime_checkable


class DependencyUnavailableError(RuntimeError):
    """Raised when an injected infrastructure dependency cannot serve a request."""


@runtime_checkable
class ObjectStore(Protocol):
    def is_ready(self) -> bool:
        """Return whether the object store can accept/read requests."""

    def put(self, key: str, content: bytes, *, media_type: str) -> str:
        """Persist bytes and return the provider key."""

    def get(self, key: str) -> bytes:
        """Read bytes by provider key."""


@runtime_checkable
class JobQueue(Protocol):
    def is_ready(self) -> bool:
        """Return whether the queue can accept work."""

    def enqueue(self, job_id: str, payload: Mapping[str, str]) -> None:
        """Enqueue metadata-only work for a processing job."""


@dataclass
class InMemoryObjectStore:
    """Local object-store double; never use for production PHI."""

    available: bool = True
    _objects: dict[str, bytes] = field(default_factory=dict)

    def is_ready(self) -> bool:
        return self.available

    def put(self, key: str, content: bytes, *, media_type: str) -> str:
        if not self.available:
            raise DependencyUnavailableError("object store is unavailable")
        if not key.strip():
            raise ValueError("object-store key is required")
        if not isinstance(content, bytes):
            raise TypeError("object-store content must be bytes")
        self._objects[key] = content
        return key

    def get(self, key: str) -> bytes:
        if not self.available:
            raise DependencyUnavailableError("object store is unavailable")
        return self._objects[key]


@dataclass
class InMemoryJobQueue:
    """Local queue double holding metadata-only payloads in process memory."""

    available: bool = True
    entries: list[tuple[str, dict[str, str]]] = field(default_factory=list)

    def is_ready(self) -> bool:
        return self.available

    def enqueue(self, job_id: str, payload: Mapping[str, str]) -> None:
        if not self.available:
            raise DependencyUnavailableError("job queue is unavailable")
        self.entries.append((job_id, {str(key): str(value) for key, value in payload.items()}))
