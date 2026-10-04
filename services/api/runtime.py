"""Provider-neutral runtime composition for local and staging.

The factory in this module is deliberately local-only. Production startup must
inject approved provider implementations through the same protocols after the
Issue #37 decision register is accepted.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .dependencies import JobQueue, ObjectStore, SQLiteJobQueue, SQLiteObjectStore
from .lifecycle import (
    DeletionCoordinator,
    InMemoryDeletionCoordinator,
    InMemoryRetentionPolicy,
    RetentionPolicy,
)
from .store import MetadataStore, SQLiteMetadataStore


def _dependency_ready(dependency: Any) -> bool:
    if dependency is None:
        return False
    try:
        return bool(dependency.is_ready())
    except Exception:
        return False


@dataclass
class RuntimeDependencies:
    """The complete dependency graph required by staging and readiness."""

    metadata_store: MetadataStore
    object_store: ObjectStore
    job_queue: JobQueue
    retention_policy: RetentionPolicy
    deletion_coordinator: DeletionCoordinator

    def readiness(self) -> dict[str, object]:
        checks = {
            "metadata_store": _dependency_ready(self.metadata_store),
            "object_store": _dependency_ready(self.object_store),
            "job_queue": _dependency_ready(self.job_queue),
            "retention_policy": _dependency_ready(self.retention_policy),
            "deletion_coordinator": _dependency_ready(self.deletion_coordinator),
        }
        return {
            "status": "ready" if all(checks.values()) else "not_ready",
            "checks": checks,
        }

    def is_ready(self) -> bool:
        return bool(self.readiness()["status"] == "ready")

    def close(self) -> None:
        """Close local adapters without assuming provider-specific methods."""
        for dependency in (
            self.metadata_store,
            self.object_store,
            self.job_queue,
            self.retention_policy,
            self.deletion_coordinator,
        ):
            close = getattr(dependency, "close", None)
            if callable(close):
                close()

    def __enter__(self) -> "RuntimeDependencies":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def build_local_runtime(root: str | Path) -> RuntimeDependencies:
    """Build a synthetic-data-only SQLite runtime outside the repository."""
    root_path = Path(root)
    root_path.mkdir(parents=True, exist_ok=True)
    retention_policy = InMemoryRetentionPolicy()
    return RuntimeDependencies(
        metadata_store=SQLiteMetadataStore(root_path / "metadata.sqlite3"),
        object_store=SQLiteObjectStore(root_path / "objects.sqlite3"),
        job_queue=SQLiteJobQueue(root_path / "queue.sqlite3"),
        retention_policy=retention_policy,
        deletion_coordinator=InMemoryDeletionCoordinator(retention_policy),
    )
