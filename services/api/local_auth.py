"""Small, signed local staging identity provider.

This module is intentionally limited to the de-identified local staging
environment. It is not an OAuth server and must not be used for production
credentials. Access and refresh tokens are signed JWTs; the configured
username/password and signing secret are read only from the process
environment and are never logged or returned in errors.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from .models import AuthContext, PrincipalRole, Scope


class LocalAuthError(PermissionError):
    """Raised when a staging credential or token cannot be accepted."""


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


@dataclass(frozen=True)
class LocalAuthSettings:
    username: str
    password: str
    secret: str
    issuer: str = "local-staging"
    audience: str = "patient-app"
    access_ttl_seconds: int = 900
    refresh_ttl_seconds: int = 2_592_000
    subject: str = "staging-patient"

    @classmethod
    def from_environment(cls, env: Mapping[str, str] | None = None) -> "LocalAuthSettings":
        values = os.environ if env is None else env
        username = values.get("STAGING_AUTH_USERNAME", "").strip()
        password = values.get("STAGING_AUTH_PASSWORD", "")
        secret = values.get("STAGING_AUTH_SECRET", "")
        if not username or not password or len(secret) < 32:
            raise LocalAuthError("local staging authentication is not configured")
        try:
            access_ttl = int(values.get("STAGING_AUTH_ACCESS_TTL_SECONDS", "900"))
            refresh_ttl = int(values.get("STAGING_AUTH_REFRESH_TTL_SECONDS", "2592000"))
        except ValueError as exc:
            raise LocalAuthError("local staging authentication TTL is invalid") from exc
        if access_ttl < 30 or refresh_ttl < access_ttl:
            raise LocalAuthError("local staging authentication TTL is invalid")
        return cls(
            username=username,
            password=password,
            secret=secret,
            issuer=values.get("STAGING_AUTH_ISSUER", "local-staging"),
            audience=values.get("STAGING_AUTH_AUDIENCE", "patient-app"),
            access_ttl_seconds=access_ttl,
            refresh_ttl_seconds=refresh_ttl,
            subject=values.get("STAGING_AUTH_SUBJECT", "staging-patient"),
        )


class LocalAuthProvider:
    """Issue and verify short-lived local staging tokens."""

    def __init__(self, settings: LocalAuthSettings) -> None:
        self.settings = settings
        self._revoked_refresh: set[str] = set()
        self._lock = threading.Lock()

    def _sign(self, encoded_header: str, encoded_payload: str) -> str:
        signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
        digest = hmac.new(self.settings.secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
        return _b64(digest)

    def _issue(self, *, subject: str, token_type: str, ttl_seconds: int) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "iss": self.settings.issuer,
            "aud": self.settings.audience,
            "sub": subject,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
            "typ": token_type,
            "jti": secrets.token_urlsafe(18),
            "roles": [PrincipalRole.PATIENT.value],
            "scopes": [scope.value for scope in Scope],
        }
        header = _b64(_json({"alg": "HS256", "typ": "JWT"}).encode("utf-8"))
        encoded_payload = _b64(_json(payload).encode("utf-8"))
        return f"{header}.{encoded_payload}.{self._sign(header, encoded_payload)}"

    def _decode(self, token: str, expected_type: str) -> Mapping[str, Any]:
        parts = token.split(".")
        if len(parts) != 3:
            raise LocalAuthError("token is invalid")
        header_part, payload_part, signature = parts
        expected_signature = self._sign(header_part, payload_part)
        if not hmac.compare_digest(signature, expected_signature):
            raise LocalAuthError("token is invalid")
        try:
            header = json.loads(_unb64(header_part))
            payload = json.loads(_unb64(payload_part))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LocalAuthError("token is invalid") from exc
        if header.get("alg") != "HS256" or payload.get("typ") != expected_type:
            raise LocalAuthError("token is invalid")
        if payload.get("iss") != self.settings.issuer or payload.get("aud") != self.settings.audience:
            raise LocalAuthError("token is invalid")
        if not isinstance(payload.get("sub"), str) or not payload["sub"].strip():
            raise LocalAuthError("token is invalid")
        try:
            if int(payload["exp"]) <= int(datetime.now(timezone.utc).timestamp()):
                raise LocalAuthError("token has expired")
        except (KeyError, TypeError, ValueError) as exc:
            raise LocalAuthError("token is invalid") from exc
        return payload

    def authenticate(self, username: str, password: str, *, request_id: str) -> Mapping[str, Any]:
        if not isinstance(username, str) or not isinstance(password, str):
            raise LocalAuthError("credentials are invalid")
        username_ok = hmac.compare_digest(username.strip(), self.settings.username)
        password_ok = hmac.compare_digest(password, self.settings.password)
        if not username_ok or not password_ok:
            raise LocalAuthError("credentials are invalid")
        access_token = self._issue(subject=self.settings.subject, token_type="access", ttl_seconds=self.settings.access_ttl_seconds)
        refresh_token = self._issue(subject=self.settings.subject, token_type="refresh", ttl_seconds=self.settings.refresh_ttl_seconds)
        access_claims = self._decode(access_token, "access")
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "Bearer",
            "expires_at": datetime.fromtimestamp(int(access_claims["exp"]), tz=timezone.utc).isoformat(),
            "subject": self.settings.subject,
            "request_id": request_id,
        }

    def refresh(self, refresh_token: str, *, request_id: str) -> Mapping[str, Any]:
        claims = self._decode(refresh_token, "refresh")
        jti = claims.get("jti")
        if not isinstance(jti, str):
            raise LocalAuthError("token is invalid")
        with self._lock:
            if jti in self._revoked_refresh:
                raise LocalAuthError("refresh token has been revoked")
            self._revoked_refresh.add(jti)
        access_token = self._issue(subject=str(claims["sub"]), token_type="access", ttl_seconds=self.settings.access_ttl_seconds)
        rotated_refresh = self._issue(subject=str(claims["sub"]), token_type="refresh", ttl_seconds=self.settings.refresh_ttl_seconds)
        return {
            "access_token": access_token,
            "refresh_token": rotated_refresh,
            "token_type": "Bearer",
            "expires_at": datetime.fromtimestamp(int(json.loads(_unb64(access_token.split(".")[1]))["exp"]), tz=timezone.utc).isoformat(),
            "subject": str(claims["sub"]),
            "request_id": request_id,
        }

    def revoke(self, refresh_token: str) -> None:
        claims = self._decode(refresh_token, "refresh")
        jti = claims.get("jti")
        if not isinstance(jti, str):
            raise LocalAuthError("token is invalid")
        with self._lock:
            self._revoked_refresh.add(jti)

    def context(self, access_token: str, *, request_id: str) -> AuthContext:
        claims = self._decode(access_token, "access")
        try:
            roles = frozenset(PrincipalRole(value) for value in claims.get("roles", []))
            scopes = frozenset(Scope(value) for value in claims.get("scopes", []))
            expires_at = datetime.fromtimestamp(int(claims["exp"]), tz=timezone.utc)
        except (TypeError, ValueError, KeyError) as exc:
            raise LocalAuthError("token claims are invalid") from exc
        return AuthContext(
            str(claims["sub"]),
            roles=roles,
            scopes=scopes,
            request_id=request_id,
            issuer=self.settings.issuer,
            audience=self.settings.audience,
            expires_at=expires_at,
        )
