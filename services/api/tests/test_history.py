from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from services.api.app import ApiHttpAdapter
from services.api.auth import AuthorizationError
from services.api.models import AuthContext, PrincipalRole, Scope
from services.api.service import ApiService


class AccountHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        self.service = ApiService(clock=lambda: self.now)
        read_write = frozenset({
            Scope.VISITS_READ,
            Scope.VISITS_WRITE,
            Scope.TASKS_READ,
            Scope.TASKS_WRITE,
        })
        self.owner = AuthContext("patient-1", roles=frozenset({PrincipalRole.PATIENT}), scopes=read_write, request_id="history-owner")
        self.other = AuthContext("patient-2", roles=frozenset({PrincipalRole.PATIENT}), scopes=read_write, request_id="history-other")
        self.reviewer = AuthContext("reviewer-1", roles=frozenset({PrincipalRole.REVIEWER}), scopes=frozenset({Scope.VISITS_READ, Scope.TASKS_READ}), request_id="history-reviewer")
        self.http = ApiHttpAdapter(self.service)

    def _seed(self) -> dict[str, object]:
        first_topic = self.service.create_topic(self.owner, name="First synthetic topic", idempotency_key="history-topic-001")
        self.now += timedelta(minutes=1)
        other_topic = self.service.create_topic(self.other, name="Other synthetic topic", idempotency_key="history-topic-002")
        self.now += timedelta(minutes=1)
        second_topic = self.service.create_topic(self.owner, name="Second synthetic topic", idempotency_key="history-topic-003")
        self.now += timedelta(minutes=1)
        first_visit = self.service.create_visit(self.owner, title="First synthetic visit", starts_at=None, topic_ids=(first_topic.id,), idempotency_key="history-visit-001")
        self.now += timedelta(minutes=1)
        other_visit = self.service.create_visit(self.other, title="Other synthetic visit", starts_at=None, topic_ids=(other_topic.id,), idempotency_key="history-visit-002")
        self.now += timedelta(minutes=1)
        second_visit = self.service.create_visit(self.owner, title="Second synthetic visit", starts_at=None, topic_ids=(second_topic.id,), idempotency_key="history-visit-003")
        self.now += timedelta(minutes=1)
        first_task = self.service.create_task(self.owner, title="First synthetic task", visit_id=first_visit.id, due_at=None, idempotency_key="history-task-001")
        self.now += timedelta(minutes=1)
        other_task = self.service.create_task(self.other, title="Other synthetic task", visit_id=other_visit.id, due_at=None, idempotency_key="history-task-002")
        self.now += timedelta(minutes=1)
        second_task = self.service.create_task(self.owner, title="Second synthetic task", visit_id=second_visit.id, due_at=None, idempotency_key="history-task-003")
        return {"first_topic": first_topic, "other_topic": other_topic, "second_topic": second_topic, "first_visit": first_visit, "other_visit": other_visit, "second_visit": second_visit, "first_task": first_task, "other_task": other_task, "second_task": second_task}

    def test_empty_lists_and_owner_isolation_are_stable(self) -> None:
        self.assertEqual(self.service.list_topics(self.owner), [])
        self.assertEqual(self.service.list_visits(self.owner), [])
        self.assertEqual(self.service.list_tasks(self.owner), [])
        seeded = self._seed()
        self.assertEqual([item.id for item in self.service.list_topics(self.owner)], [seeded["first_topic"].id, seeded["second_topic"].id])
        self.assertEqual([item.id for item in self.service.list_visits(self.owner)], [seeded["first_visit"].id, seeded["second_visit"].id])
        self.assertEqual([item.id for item in self.service.list_tasks(self.owner)], [seeded["first_task"].id, seeded["second_task"].id])
        self.assertEqual([item.id for item in self.service.list_topics(self.reviewer)], [seeded["first_topic"].id, seeded["other_topic"].id, seeded["second_topic"].id])
        self.assertEqual([item.id for item in self.service.list_visits(self.reviewer)], [seeded["first_visit"].id, seeded["other_visit"].id, seeded["second_visit"].id])
        self.assertEqual([item.id for item in self.service.list_tasks(self.reviewer)], [seeded["first_task"].id, seeded["other_task"].id, seeded["second_task"].id])

    def test_read_scopes_are_required_for_each_collection(self) -> None:
        writes_only = AuthContext("patient-3", roles=frozenset({PrincipalRole.PATIENT}), scopes=frozenset({Scope.VISITS_WRITE, Scope.TASKS_WRITE}), request_id="history-no-read")
        with self.assertRaises(AuthorizationError):
            self.service.list_topics(writes_only)
        with self.assertRaises(AuthorizationError):
            self.service.list_visits(writes_only)
        with self.assertRaises(AuthorizationError):
            self.service.list_tasks(writes_only)

    def test_http_routes_return_arrays_and_preserve_boundary(self) -> None:
        seeded = self._seed()
        owner_scopes = "visits:read,tasks:read"
        owner_headers = {"Authorization": f"Bearer patient-1|{owner_scopes}|patient"}
        other_headers = {"Authorization": "Bearer patient-2|visits:read,tasks:read|patient"}
        reviewer_headers = {"Authorization": "Bearer reviewer-1|visits:read,tasks:read|reviewer"}
        for route in ("/v1/topics", "/v1/visits", "/v1/tasks"):
            no_auth = self.http.handle("GET", route)
            self.assertEqual(no_auth.status_code, 401)
            self.assertEqual(no_auth.body["code"], "AUTHENTICATION_REQUIRED")
        self.assertEqual([item["id"] for item in self.http.handle("GET", "/v1/topics", headers=owner_headers).body], [seeded["first_topic"].id, seeded["second_topic"].id])
        self.assertEqual([item["id"] for item in self.http.handle("GET", "/v1/visits", headers=other_headers).body], [seeded["other_visit"].id])
        self.assertEqual([item["id"] for item in self.http.handle("GET", "/v1/tasks", headers=reviewer_headers).body], [seeded["first_task"].id, seeded["other_task"].id, seeded["second_task"].id])
        forbidden = self.http.handle("GET", "/v1/topics", headers={"Authorization": "Bearer patient-1|documents:read|patient"})
        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(forbidden.body["code"], "FORBIDDEN")


if __name__ == "__main__":
    unittest.main()
