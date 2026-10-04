"""Provider-neutral retention and deletion lifecycle seams.

The in-memory implementations model staging state transitions only. Production
adapters must fan out to every approved store, queue, cache and eligible backup
with a durable completion ledger.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import Enum
from typing import Mapping, Protocol
import uuid

from .dependencies import DependencyUnavailableError


DEFAULT_RETENTION_DAYS = 30
REQUIRED_DELETION_TARGETS = frozenset(
    {"metadata", "object_store", "job_queue", "protected_cache", "eligible_backups"}
)


class DeletionState(str, Enum):
    BLOCKED_LEGAL_HOLD = "blocked_legal_hold"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class DeletionTargetState(str, Enum):
    PENDING = "pending"
    FAILED = "failed"
    COMPLETED = "completed"


class DeletionBlockedError(RuntimeError):
    """Raised when a deletion is blocked by an active legal hold."""


class RetentionPolicy(Protocol):
    def is_ready(self) -> bool:
        """Return whether retention and legal-hold decisions can be evaluated."""

    def retention_deadline(self, resource_type: str, created_at: datetime) -> datetime:
        """Return the deletion eligibility deadline for a resource."""

    def deletion_block_reason(self, subject_id: str) -> str | None:
        """Return a stable reason when deletion must remain blocked."""


class DeletionCoordinator(Protocol):
    def is_ready(self) -> bool:
        """Return whether the deletion ledger and all policy dependencies are ready."""

    def request(self, subject_id: str, request_id: str, now: datetime) -> "DeletionReceipt":
        """Create or replay an idempotent deletion request."""

    def resume(self, deletion_id: str, now: datetime) -> "DeletionReceipt":
        """Resume a request after a legal hold is released."""

    def mark_target(
        self,
        deletion_id: str,
        target: str,
        *,
        completed: bool,
        now: datetime,
    ) -> "DeletionReceipt":
        """Record one target result and return the current completion ledger."""

    def get(self, deletion_id: str) -> "DeletionReceipt":
        """Read one deletion completion ledger."""


@dataclass(frozen=True)
class DeletionReceipt:
    id: str
    subject_id: str
    request_id: str
    state: DeletionState
    target_states: Mapping[str, DeletionTargetState]
    requested_at: datetime
    completed_at: datetime | None = None


@dataclass
class InMemoryRetentionPolicy:
    """Synthetic retention policy for local/staging contract tests."""

    default_days: int = DEFAULT_RETENTION_DAYS
    overrides: dict[str, int] = field(default_factory=dict)
    legal_holds: set[str] = field(default_factory=set)
    available: bool = True

    def __post_init__(self) -> None:
        if self.default_days < 1:
            raise ValueError("default retention must be positive")
        if any(days < 1 for days in self.overrides.values()):
            raise ValueError("retention overrides must be positive")

    def is_ready(self) -> bool:
        return self.available

    def _ensure_ready(self) -> None:
        if not self.available:
            raise DependencyUnavailableError("retention policy is unavailable")

    def retention_deadline(self, resource_type: str, created_at: datetime) -> datetime:
        self._ensure_ready()
        if not resource_type.strip():
            raise ValueError("resource type is required")
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        days = self.overrides.get(resource_type, self.default_days)
        return created_at + timedelta(days=days)

    def deletion_block_reason(self, subject_id: str) -> str | None:
        self._ensure_ready()
        if not subject_id.strip():
            raise ValueError("subject id is required")
        return "legal_hold" if subject_id in self.legal_holds else None


class InMemoryDeletionCoordinator:
    """Synthetic cross-store deletion ledger for local/staging tests.

    It never deletes bytes. A production replacement must stop new work, fan out
    to every approved target, preserve legal holds, and make completion
    observable and resumable.
    """

    def __init__(
        self,
        retention_policy: RetentionPolicy,
        *,
        required_targets: frozenset[str] = REQUIRED_DELETION_TARGETS,
        available: bool = True,
    ) -> None:
        if not required_targets:
            raise ValueError("at least one deletion target is required")
        self.retention_policy = retention_policy
        self.required_targets = frozenset(required_targets)
        self.available = available
        self._receipts: dict[str, DeletionReceipt] = {}
        self._requests: dict[tuple[str, str], str] = {}

    def is_ready(self) -> bool:
        if not self.available:
            return False
        try:
            return bool(self.retention_policy.is_ready())
        except Exception:
            return False

    def _ensure_ready(self) -> None:
        if not self.is_ready():
            raise DependencyUnavailableError("deletion coordinator is unavailable")

    @staticmethod
    def _validate_request(subject_id: str, request_id: str, now: datetime) -> None:
        if not subject_id.strip() or not request_id.strip():
            raise ValueError("subject and request identifiers are required")
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("deletion time must include a timezone")

    def request(self, subject_id: str, request_id: str, now: datetime) -> DeletionReceipt:
        self._ensure_ready()
        self._validate_request(subject_id, request_id, now)
        request_key = (subject_id, request_id)
        existing_id = self._requests.get(request_key)
        if existing_id is not None:
            return self._receipts[existing_id]
        blocked = self.retention_policy.deletion_block_reason(subject_id) is not None
        receipt = DeletionReceipt(
            id=str(uuid.uuid4()),
            subject_id=subject_id,
            request_id=request_id,
            state=DeletionState.BLOCKED_LEGAL_HOLD if blocked else DeletionState.IN_PROGRESS,
            target_states={target: DeletionTargetState.PENDING for target in self.required_targets},
            requested_at=now,
        )
        self._requests[request_key] = receipt.id
        self._receipts[receipt.id] = receipt
        return receipt

    def get(self, deletion_id: str) -> DeletionReceipt:
        self._ensure_ready()
        try:
            return self._receipts[deletion_id]
        except KeyError as exc:
            raise KeyError("deletion request not found") from exc

    def resume(self, deletion_id: str, now: datetime) -> DeletionReceipt:
        self._ensure_ready()
        receipt = self.get(deletion_id)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("deletion time must include a timezone")
        if receipt.state != DeletionState.BLOCKED_LEGAL_HOLD:
            return receipt
        if self.retention_policy.deletion_block_reason(receipt.subject_id) is not None:
            raise DeletionBlockedError("deletion is blocked by legal hold")
        resumed = replace(receipt, state=DeletionState.IN_PROGRESS)
        self._receipts[deletion_id] = resumed
        return resumed

    def mark_target(
        self,
        deletion_id: str,
        target: str,
        *,
        completed: bool,
        now: datetime,
    ) -> DeletionReceipt:
        self._ensure_ready()
        receipt = self.get(deletion_id)
        if target not in self.required_targets:
            raise ValueError("unknown deletion target")
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("deletion time must include a timezone")
        if receipt.state == DeletionState.BLOCKED_LEGAL_HOLD:
            raise DeletionBlockedError("deletion is blocked by legal hold")
        if receipt.state == DeletionState.COMPLETED:
            return receipt
        states = dict(receipt.target_states)
        states[target] = DeletionTargetState.COMPLETED if completed else DeletionTargetState.FAILED
        state = (
            DeletionState.COMPLETED
            if all(value == DeletionTargetState.COMPLETED for value in states.values())
            else DeletionState.IN_PROGRESS
        )
        updated = replace(
            receipt,
            state=state,
            target_states=states,
            completed_at=now if state == DeletionState.COMPLETED else None,
        )
        self._receipts[deletion_id] = updated
        return updated
