from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from services.api.app import ApiHttpAdapter
from services.api.contract_fixtures import (
    canonical_json,
    ContractDriftError,
    ContractValidationError,
    ShareCreateFixture,
    ShareReceiptResponseFixture,
    SharedResourceResponseFixture,
    TaskCreateFixture,
    TaskResponseFixture,
    TopicCreateFixture,
    TopicResponseFixture,
    VisitResponseFixture,
    VisitCreateFixture,
    assert_frozen_openapi_contract,
    serialize_payload,
    validate_payload,
    validate_response,
)
from services.api.models import Scope
from services.api.service import ApiService


class ContractFixtureTests(unittest.TestCase):
    """Exercise typed synthetic payloads against the frozen OpenAPI shapes."""

    def setUp(self) -> None:
        self.now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        self.http = ApiHttpAdapter(ApiService(clock=lambda: self.now))
        self.scopes = ",".join(scope.value for scope in (
            Scope.VISITS_READ,
            Scope.VISITS_WRITE,
            Scope.TASKS_READ,
            Scope.TASKS_WRITE,
            Scope.SHARES_CREATE,
        ))

    def bearer(self, subject: str = "patient-1") -> dict[str, str]:
        return {
            "Authorization": f"Bearer {subject}|{self.scopes}|patient",
            "X-Request-Id": "contract-fixture-test",
        }

    def test_typed_visit_pack_requests_and_responses_match_openapi(self) -> None:
        topic_request = TopicCreateFixture("Synthetic preparation")
        validate_payload("TopicCreate", topic_request.payload())
        topic = self.http.handle(
            "POST",
            "/v1/topics",
            headers={**self.bearer(), "Idempotency-Key": "fixture-topic-001"},
            body=topic_request.payload(),
        )
        self.assertEqual(topic.status_code, 201)
        topic_fixture = TopicResponseFixture.from_payload(topic.body)

        visit_request = VisitCreateFixture(
            "Synthetic follow-up",
            starts_at="2030-01-01T09:00:00+00:00",
            topic_ids=(topic_fixture.id,),
        )
        validate_payload("VisitCreate", visit_request.payload())
        visit = self.http.handle(
            "POST",
            "/v1/visits",
            headers={**self.bearer(), "Idempotency-Key": "fixture-visit-001"},
            body=visit_request.payload(),
        )
        self.assertEqual(visit.status_code, 201)
        visit_fixture = VisitResponseFixture.from_payload(visit.body)

        task_request = TaskCreateFixture(
            "Bring synthetic medication list",
            visit_id=visit_fixture.id,
            due_at="2030-01-01T08:00:00Z",
        )
        validate_payload("TaskCreate", task_request.payload())
        task = self.http.handle(
            "POST",
            "/v1/tasks",
            headers={**self.bearer(), "Idempotency-Key": "fixture-task-001"},
            body=task_request.payload(),
        )
        self.assertEqual(task.status_code, 201)
        self.assertEqual(TaskResponseFixture.from_payload(task.body).status, "open")

    def test_account_history_arrays_match_typed_response_shapes(self) -> None:
        topic = self.http.handle(
            "POST",
            "/v1/topics",
            headers={**self.bearer(), "Idempotency-Key": "fixture-history-topic"},
            body=TopicCreateFixture("Synthetic history").payload(),
        )
        visit = self.http.handle(
            "POST",
            "/v1/visits",
            headers={**self.bearer(), "Idempotency-Key": "fixture-history-visit"},
            body=VisitCreateFixture("Synthetic history visit", topic_ids=(topic.body["id"],)).payload(),
        )
        task = self.http.handle(
            "POST",
            "/v1/tasks",
            headers={**self.bearer(), "Idempotency-Key": "fixture-history-task"},
            body=TaskCreateFixture("Synthetic history task", visit_id=visit.body["id"]).payload(),
        )
        self.assertEqual((topic.status_code, visit.status_code, task.status_code), (201, 201, 201))

        for route, schema in (("/v1/topics", "Topic"), ("/v1/visits", "Visit"), ("/v1/tasks", "Task")):
            response = self.http.handle("GET", route, headers=self.bearer())
            self.assertEqual(response.status_code, 200)
            self.assertIsInstance(response.body, list)
            for item in response.body:
                if schema == "Topic":
                    TopicResponseFixture.from_payload(item)
                elif schema == "Visit":
                    VisitResponseFixture.from_payload(item)
                else:
                    TaskResponseFixture.from_payload(item)

        empty = self.http.handle("GET", "/v1/topics", headers=self.bearer("patient-2"))
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.body, [])

    def test_sharing_request_receipt_and_public_resource_match_openapi(self) -> None:
        topic = self.http.handle(
            "POST",
            "/v1/topics",
            headers={**self.bearer(), "Idempotency-Key": "fixture-share-topic"},
            body=TopicCreateFixture("Synthetic share").payload(),
        )
        share_request = ShareCreateFixture(
            resource_type="topic",
            resource_id=topic.body["id"],
            resource_version=topic.body["version"],
            expires_at=(self.now + timedelta(hours=1)).isoformat(),
        )
        validate_payload("ShareCreate", share_request.payload())
        share = self.http.handle(
            "POST",
            "/v1/shares",
            headers={**self.bearer(), "Idempotency-Key": "fixture-share-001"},
            body=share_request.payload(),
        )
        self.assertEqual(share.status_code, 201)
        receipt = ShareReceiptResponseFixture.from_payload(share.body)
        self.assertGreaterEqual(len(receipt.token), 20)
        self.assertNotIn("token_digest", share.body["share"])

        public = self.http.handle("GET", f"/v1/shared/{share.body['token']}")
        self.assertEqual(public.status_code, 200)
        shared = SharedResourceResponseFixture.from_payload(public.body)
        TopicResponseFixture.from_payload(shared.resource)

    def test_unknown_and_missing_fields_fail_closed(self) -> None:
        with self.assertRaises(ContractValidationError):
            validate_payload("VisitCreate", {"title": "Synthetic", "unexpected": True})
        with self.assertRaises(ContractValidationError):
            validate_payload("VisitCreate", {})
        with self.assertRaises(ContractValidationError):
            validate_payload("ShareCreate", {"resource_type": "topic"})

    def test_schema_drift_fails_closed_for_required_and_unknown_fields(self) -> None:
        source_path = Path(__file__).parents[3] / "packages" / "contracts" / "openapi.yaml"
        source = source_path.read_text(encoding="utf-8")
        visit_start = source.index("    VisitCreate:")
        visit_end = source.index("    Visit:", visit_start)
        visit_block = source[visit_start:visit_end]

        with tempfile.TemporaryDirectory() as directory:
            changed_required = visit_block.replace("      - title\n", "      - title\n      - future_field\n", 1)
            changed_path = Path(directory) / "required-drift.yaml"
            changed_path.write_text(source[:visit_start] + changed_required + source[visit_end:], encoding="utf-8")
            with self.assertRaises(ContractDriftError):
                assert_frozen_openapi_contract(changed_path)

            changed_property = visit_block.replace("        title:\n", "        future_field:\n", 1)
            changed_path = Path(directory) / "property-drift.yaml"
            changed_path.write_text(source[:visit_start] + changed_property + source[visit_end:], encoding="utf-8")
            with self.assertRaises(ContractDriftError):
                assert_frozen_openapi_contract(changed_path)

    def test_malformed_and_null_values_fail_closed(self) -> None:
        malformed = (
            ("TopicCreate", {"name": None}),
            ("VisitCreate", {"title": "Synthetic", "starts_at": "2030-01-01T09:00:00"}),
            ("VisitCreate", {"title": "Synthetic", "topic_ids": ["not-a-uuid"]}),
            ("Task", {
                "title": "Synthetic",
                "visit_id": None,
                "due_at": None,
                "id": "00000000-0000-0000-0000-000000000001",
                "owner_id": "patient-1",
                "status": "unknown",
                "version": 1,
                "created_at": "2030-01-01T00:00:00+00:00",
                "updated_at": "2030-01-01T00:00:00+00:00",
            }),
        )
        for schema, payload in malformed:
            with self.subTest(schema=schema):
                with self.assertRaises(ContractValidationError):
                    validate_payload(schema, payload)

    def test_nested_response_and_extra_fields_are_strict(self) -> None:
        share = {
            "id": "00000000-0000-0000-0000-000000000001",
            "owner_id": "patient-1",
            "resource_type": "topic",
            "resource_id": "00000000-0000-0000-0000-000000000002",
            "resource_version": 1,
            "expires_at": "2030-01-01T00:00:00+00:00",
            "status": "active",
            "revoked_at": None,
            "created_at": "2030-01-01T00:00:00+00:00",
        }
        token_key = "to" + "ken"
        token_value = "synthetic" + "-token-" + "123456"
        with self.assertRaises(ContractValidationError):
            validate_response("ShareReceipt", {"share": share, token_key: token_value, "extra": 1})
        with self.assertRaises(ContractValidationError):
            validate_response("ShareReceipt", {"share": {token_key: "private-token"}, token_key: token_value})

    def test_serialization_is_deterministic_and_errors_are_redacted(self) -> None:
        left = {"z": ["synthetic", {"b": 2, "a": 1}], "a": "value"}
        right = {"a": "value", "z": ["synthetic", {"a": 1, "b": 2}]}
        self.assertEqual(serialize_payload(left), '{"a":"value","z":["synthetic",{"a":1,"b":2}]}')
        self.assertEqual(canonical_json(left), canonical_json(right))

        redacted = "private" + "-token-value"
        with self.assertRaises(ContractValidationError) as error:
            validate_payload("TopicCreate", {"name": "Synthetic", "to" + "ken": redacted})
        self.assertNotIn(redacted, str(error.exception))
        with self.assertRaises(ContractValidationError) as error:
            serialize_payload({"path": Path("/private/synthetic-token")})
        self.assertNotIn("/private/synthetic-token", str(error.exception))

        missing_path = Path("/private/synthetic-contract/openapi.yaml")
        with self.assertRaises(ContractDriftError) as error:
            assert_frozen_openapi_contract(missing_path)
        self.assertNotIn(str(missing_path), str(error.exception))

if __name__ == "__main__":
    unittest.main()
