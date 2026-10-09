import unittest

from services.api.app import ApiHttpAdapter
from services.api.local_auth import LocalAuthError, LocalAuthProvider, LocalAuthSettings


class LocalAuthProviderTests(unittest.TestCase):
    def setUp(self):
        self.provider = LocalAuthProvider(LocalAuthSettings("demo", "correct horse", "x" * 48, access_ttl_seconds=60, refresh_ttl_seconds=120))

    def test_issue_verify_refresh_and_revoke(self):
        issued = self.provider.authenticate("demo", "correct horse", request_id="r1")
        context = self.provider.context(issued["access_token"], request_id="r2")
        self.assertEqual(context.subject_id, "staging-patient")
        refreshed = self.provider.refresh(issued["refresh_token"], request_id="r3")
        self.assertEqual(refreshed["subject"], "staging-patient")
        self.assertNotEqual(refreshed["refresh_token"], issued["refresh_token"])
        with self.assertRaises(LocalAuthError):
            self.provider.refresh(issued["refresh_token"], request_id="r3-replay")
        self.provider.revoke(issued["refresh_token"])

    def test_bad_password_and_tampered_token_are_rejected(self):
        with self.assertRaises(LocalAuthError):
            self.provider.authenticate("demo", "wrong", request_id="r1")
        issued = self.provider.authenticate("demo", "correct horse", request_id="r2")
        token = issued["access_token"][:-1] + ("a" if issued["access_token"][-1] != "a" else "b")
        with self.assertRaises(LocalAuthError):
            self.provider.context(token, request_id="r3")

    def test_environment_requires_secret_and_credentials(self):
        with self.assertRaises(LocalAuthError):
            LocalAuthSettings.from_environment({"STAGING_AUTH_USERNAME": "demo", "STAGING_AUTH_PASSWORD": "secret", "STAGING_AUTH_SECRET": "short"})

    def test_http_adapter_exposes_session_refresh_and_logout_without_temporary_bearer(self):
        adapter = ApiHttpAdapter(auth_provider=self.provider)
        issued = adapter.handle("POST", "/v1/auth/sessions", body={"username": "demo", "password": "correct horse"})
        self.assertEqual(issued.status_code, 200)
        access = issued.body["access_token"]
        refresh = issued.body["refresh_token"]
        response = adapter.handle("GET", "/v1/documents", headers={"Authorization": f"Bearer {access}"})
        self.assertEqual(response.status_code, 200)
        logged_out = adapter.handle("POST", "/v1/auth/logout", body={"refresh_token": refresh})
        self.assertEqual(logged_out.status_code, 204)


if __name__ == "__main__":
    unittest.main()
