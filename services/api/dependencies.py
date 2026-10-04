"""Replaceable infrastructure boundaries for the local API skeleton.

Queue messages remain metadata-only; object storage accepts bounded binary content.
Production adapters may
back them with encrypted object storage and a durable queue, but the core service
never needs to know which provider is used.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, field
from typing import Mapping, Protocol, runtime_checkable

from .sqlite_schema import UnsupportedSchemaVersionError, ensure_schema_version


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


class SQLiteObjectStore:
    """Restart-safe local/staging object adapter; use encrypted managed storage for PHI."""

    def __init__(self, path: str | Path, *, available: bool = True) -> None:
        self.path = str(path)
        self.available = available
        self._connection: sqlite3.Connection | None = None
        if self.available:
            try:
                self._connection = sqlite3.connect(self.path, check_same_thread=False)
                self._initialize()
            except (OSError, sqlite3.Error, UnsupportedSchemaVersionError) as exc:
                self.close()
                raise DependencyUnavailableError("object store is unavailable") from exc

    def _initialize(self) -> None:
        connection = self._connection
        if connection is None:
            raise DependencyUnavailableError("object store is unavailable")

        def initialize(connection: sqlite3.Connection) -> None:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS objects (object_key TEXT PRIMARY KEY, media_type TEXT NOT NULL, content BLOB NOT NULL, created_at TEXT NOT NULL)"
            )

        ensure_schema_version(connection, current_version=1, initialize=initialize)

    def _require_connection(self) -> sqlite3.Connection:
        if not self.available or self._connection is None:
            raise DependencyUnavailableError("object store is unavailable")
        return self._connection

    def is_ready(self) -> bool:
        if not self.available or self._connection is None:
            return False
        try:
            self._connection.execute("SELECT 1").fetchone()
            return True
        except sqlite3.Error:
            return False

    def put(self, key: str, content: bytes, *, media_type: str) -> str:
        connection = self._require_connection()
        if not key.strip():
            raise ValueError("object-store key is required")
        if not isinstance(content, bytes):
            raise TypeError("object-store content must be bytes")
        with connection:
            connection.execute(
                "INSERT OR REPLACE INTO objects(object_key, media_type, content, created_at) VALUES (?, ?, ?, ?)",
                (key, media_type, content, datetime.now(timezone.utc).isoformat()),
            )
        return key

    def get(self, key: str) -> bytes:
        connection = self._require_connection()
        row = connection.execute("SELECT content FROM objects WHERE object_key = ?", (key,)).fetchone()
        if row is None:
            raise KeyError("object not found")
        return bytes(row[0])

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> "SQLiteObjectStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class SQLiteJobQueue:
    """Restart-safe metadata-only queue adapter for local/staging workflows."""

    def __init__(self, path: str | Path, *, available: bool = True) -> None:
        self.path = str(path)
        self.available = available
        self._connection: sqlite3.Connection | None = None
        if self.available:
            try:
                self._connection = sqlite3.connect(self.path, check_same_thread=False)
                self._initialize()
            except (OSError, sqlite3.Error, UnsupportedSchemaVersionError) as exc:
                self.close()
                raise DependencyUnavailableError("job queue is unavailable") from exc

    def _initialize(self) -> None:
        connection = self._connection
        if connection is None:
            raise DependencyUnavailableError("job queue is unavailable")

        def initialize(connection: sqlite3.Connection) -> None:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS job_queue (job_id TEXT PRIMARY KEY, payload TEXT NOT NULL, enqueued_at TEXT NOT NULL)"
            )

        ensure_schema_version(connection, current_version=1, initialize=initialize)

    def _require_connection(self) -> sqlite3.Connection:
        if not self.available or self._connection is None:
            raise DependencyUnavailableError("job queue is unavailable")
        return self._connection

    def is_ready(self) -> bool:
        if not self.available or self._connection is None:
            return False
        try:
            self._connection.execute("SELECT 1").fetchone()
            return True
        except sqlite3.Error:
            return False

    def enqueue(self, job_id: str, payload: Mapping[str, str]) -> None:
        connection = self._require_connection()
        if not job_id.strip():
            raise ValueError("job id is required")
        safe_payload = {str(key): str(value) for key, value in payload.items()}
        with connection:
            connection.execute(
                "INSERT OR IGNORE INTO job_queue(job_id, payload, enqueued_at) VALUES (?, ?, ?)",
                (job_id, json.dumps(safe_payload, sort_keys=True, separators=(",", ":")), datetime.now(timezone.utc).isoformat()),
            )

    @property
    def entries(self) -> list[tuple[str, dict[str, str]]]:
        connection = self._require_connection()
        rows = connection.execute("SELECT job_id, payload FROM job_queue ORDER BY enqueued_at, job_id").fetchall()
        return [(row[0], dict(json.loads(row[1]))) for row in rows]

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> "SQLiteJobQueue":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
