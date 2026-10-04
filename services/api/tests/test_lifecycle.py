from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from services.api.dependencies import DependencyUnavailableError
from services.api.lifecycle import (
    DEFAULT_RETENTION_DAYS,
    DeletionBlockedError,
    DeletionState,
    DeletionTargetState,
    InMemoryDeletionCoordinator,
    InMemoryRetentionPolicy,
    REQUIRED_DELETION_TARGETS,
)


class LifecycleContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2030, 1, 1, tzinfo=timezone.utc)

    def test_default_retention_and_resource_override(self) -> None:
        policy = InMemoryRetentionPolicy(overrides={"audit": 90})
        self.assertEqual(
            policy.retention_deadline("document", self.now),
            self.now + timedelta(days=DEFAULT_RETENTION_DAYS),
        )
        self.assertEqual(
            policy.retention_deadline("audit", self.now),
            self.now + timedelta(days=90),
        )

    def test_legal_hold_blocks_then_resume_requires_all_targets(self) -> None:
        policy = InMemoryRetentionPolicy(legal_holds={"synthetic-subject"})
        coordinator = InMemoryDeletionCoordinator(policy)
        blocked = coordinator.request("synthetic-subject", "delete-001", self.now)
        self.assertEqual(blocked.state, DeletionState.BLOCKED_LEGAL_HOLD)
        with self.assertRaises(DeletionBlockedError):
            coordinator.mark_target(
                blocked.id,
                "metadata",
                completed=True,
                now=self.now,
            )

        policy.legal_holds.clear()
        resumed = coordinator.resume(blocked.id, self.now + timedelta(days=1))
        self.assertEqual(resumed.state, DeletionState.IN_PROGRESS)
        for target in sorted(REQUIRED_DELETION_TARGETS):
            resumed = coordinator.mark_target(
                blocked.id,
                target,
                completed=True,
                now=self.now + timedelta(days=1),
            )
        self.assertEqual(resumed.state, DeletionState.COMPLETED)
        self.assertEqual(set(resumed.target_states), REQUIRED_DELETION_TARGETS)
        self.assertTrue(resumed.completed_at)

    def test_request_and_target_completion_are_idempotent(self) -> None:
        policy = InMemoryRetentionPolicy()
        coordinator = InMemoryDeletionCoordinator(policy)
        first = coordinator.request("synthetic-subject", "delete-002", self.now)
        replay = coordinator.request("synthetic-subject", "delete-002", self.now)
        self.assertEqual(replay.id, first.id)
        failed = coordinator.mark_target(
            first.id,
            "metadata",
            completed=False,
            now=self.now,
        )
        retried = coordinator.mark_target(
            first.id,
            "metadata",
            completed=True,
            now=self.now,
        )
        self.assertEqual(failed.target_states["metadata"], DeletionTargetState.FAILED)
        self.assertEqual(retried.target_states["metadata"], DeletionTargetState.COMPLETED)

    def test_policy_and_coordinator_fail_closed_when_unavailable(self) -> None:
        policy = InMemoryRetentionPolicy(available=False)
        coordinator = InMemoryDeletionCoordinator(policy)
        self.assertFalse(coordinator.is_ready())
        with self.assertRaises(DependencyUnavailableError):
            coordinator.request("synthetic-subject", "delete-003", self.now)


if __name__ == "__main__":
    unittest.main()
