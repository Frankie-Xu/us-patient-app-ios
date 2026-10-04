from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from services.api.app import ApiHttpAdapter
from services.api.auth import GatewayClaims, GatewayClaimsError, auth_context_from_gateway_claims
from services.api.models import PrincipalRole, Scope
from services.api.service import ApiService


class GatewayClaimsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        self.valid = {
            "issuer": "https://issuer.synthetic.invalid",
            "audience": "patient-app",
            "subject": "patient-1",
            "expires_at": self.now + timedelta(minutes=5),
            "request_id": "gateway-request-001",
            "roles": ["patient"],
            "scopes": ["visits:read", "tasks:read"],
        }

    def map(self, claims: dict[str, object] | GatewayClaims):
        return auth_context_from_gateway_claims(
            claims,
            expected_issuer="https://issuer.synthetic.invalid",
            expected_audience="patient-app",
            now=lambda: self.now,
        )

    def test_valid_reviewer_and_service_claims_map_to_whitelisted_enums(self) -> None:
        reviewer = self.map({**self.valid, "roles": ["reviewer"], "scopes": ["visits:read"]})
        self.assertEqual(reviewer.subject_id, "patient-1")
        self.assertEqual(reviewer.roles, frozenset({PrincipalRole.REVIEWER}))
        self.assertEqual(reviewer.scopes, frozenset({Scope.VISITS_READ}))
        self.assertEqual(reviewer.request_id, "gateway-request-001")
        self.assertEqual(reviewer.issuer, "https://issuer.synthetic.invalid")
        service = self.map({**self.valid, "subject": "worker-1", "roles": ["service"], "scopes": ["tasks:read"]})
        self.assertEqual(service.roles, frozenset({PrincipalRole.SERVICE}))
        self.assertEqual(service.scopes, frozenset({Scope.TASKS_READ}))

    def test_expired_and_revoked_equivalent_claims_fail_closed(self) -> None:
        with self.assertRaises(GatewayClaimsError):
            self.map({**self.valid, "expires_at": self.now})
        with self.assertRaises(GatewayClaimsError):
            self.map({**self.valid, "revoked": True})
        with self.assertRaises(GatewayClaimsError):
            self.map({**self.valid, "status": "disabled"})
        with self.assertRaises(GatewayClaimsError):
            self.map({**self.valid, "active": False})

    def test_wrong_issuer_audience_and_empty_subject_fail_closed(self) -> None:
        for field, value in (("issuer", "https://evil.invalid"), ("audience", "other-app"), ("subject", "")):
            with self.subTest(field=field), self.assertRaises(GatewayClaimsError):
                self.map({**self.valid, field: value})

    def test_unknown_roles_scopes_and_malformed_claims_fail_closed(self) -> None:
        for field, value in (("roles", ["administrator"]), ("scopes", ["admin:root"]), ("request_id", ""), ("expires_at", "2030-01-01T00:00:00")):
            with self.subTest(field=field), self.assertRaises(GatewayClaimsError):
                self.map({**self.valid, field: value})
        with self.assertRaises(GatewayClaimsError):
            GatewayClaims.from_mapping({"issuer": "issuer"})
        with self.assertRaises(GatewayClaimsError):
            self.map({**self.valid, "roles": ["patient", 7]})

    def test_common_gateway_aliases_are_mapped_without_jwt_parsing(self) -> None:
        claims = {
            "iss": self.valid["issuer"],
            "aud": self.valid["audience"],
            "sub": self.valid["subject"],
            "exp": (self.now + timedelta(minutes=5)).timestamp(),
            "request_id": self.valid["request_id"],
            "roles": ["patient"],
            "scopes": ["visits:read"],
        }
        context = self.map(claims)
        self.assertEqual(context.subject_id, "patient-1")
        self.assertEqual(context.expires_at, self.now + timedelta(minutes=5))

    def test_temporary_bearer_adapter_remains_compatible(self) -> None:
        service = ApiService()
        http = ApiHttpAdapter(service)
        response = http.handle(
            "GET",
            "/v1/topics",
            headers={"Authorization": "Bearer patient-1|visits:read|patient"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.body, [])


if __name__ == "__main__":
    unittest.main()
