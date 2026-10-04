"""Authentication and authorization boundaries.

The service accepts an already-authenticated principal. JWT signature and
identity-provider verification stay in the gateway. ``GatewayClaims`` is a
provider-neutral, post-verification mapping boundary; it never parses tokens or
records token material.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping

from .models import AuthContext, PrincipalRole, Scope, utc_now


class AuthorizationError(PermissionError):
    pass


class GatewayClaimsError(PermissionError):
    """Raised when verified gateway claims cannot become a safe AuthContext."""


def _claim_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GatewayClaimsError(f"gateway claim {field} must be a non-empty string")
    return value.strip()


def _claim_values(value: Any, field: str) -> tuple[str, ...]:
    if isinstance(value, str):
        values: Iterable[Any] = (value,)
    elif isinstance(value, (list, tuple, set, frozenset)):
        values = value
    else:
        raise GatewayClaimsError(f"gateway claim {field} must be a string array")
    normalized = tuple(item.value if isinstance(item, (PrincipalRole, Scope)) else item for item in values)
    if any(not isinstance(item, str) or not item.strip() for item in normalized):
        raise GatewayClaimsError(f"gateway claim {field} contains an invalid value")
    return tuple(item.strip() for item in normalized)


def _claim_expiry(value: Any) -> datetime:
    if isinstance(value, datetime):
        expiry = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            expiry = datetime.fromtimestamp(value, tz=timezone.utc)
        except (OverflowError, OSError, ValueError) as exc:
            raise GatewayClaimsError("gateway claim expiry is invalid") from exc
    elif isinstance(value, str):
        try:
            expiry = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise GatewayClaimsError("gateway claim expiry is invalid") from exc
    else:
        raise GatewayClaimsError("gateway claim expiry is required")
    if expiry.tzinfo is None:
        raise GatewayClaimsError("gateway claim expiry must include a timezone")
    return expiry


@dataclass(frozen=True)
class GatewayClaims:
    """Typed claims supplied after gateway JWT verification.

    ``roles`` and ``scopes`` are deliberately raw strings at this boundary so
    unknown provider values can be rejected before they become authorization
    enums. ``revoked`` is a provider-neutral equivalent for a revoked principal.
    """

    issuer: str
    audience: str
    subject: str
    expires_at: datetime
    request_id: str
    roles: tuple[str, ...] = ()
    scopes: tuple[str, ...] = ()
    revoked: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "issuer", _claim_text(self.issuer, "issuer"))
        object.__setattr__(self, "audience", _claim_text(self.audience, "audience"))
        object.__setattr__(self, "subject", _claim_text(self.subject, "subject"))
        object.__setattr__(self, "request_id", _claim_text(self.request_id, "request_id"))
        object.__setattr__(self, "expires_at", _claim_expiry(self.expires_at))
        object.__setattr__(self, "roles", _claim_values(self.roles, "roles"))
        object.__setattr__(self, "scopes", _claim_values(self.scopes, "scopes"))
        if not isinstance(self.revoked, bool):
            raise GatewayClaimsError("gateway claim revoked must be boolean")

    @classmethod
    def from_mapping(cls, claims: Mapping[str, Any]) -> "GatewayClaims":
        """Map canonical or common gateway claim names without reading a JWT."""
        if not isinstance(claims, Mapping):
            raise GatewayClaimsError("gateway claims must be a mapping")
        status = claims.get("status")
        revoked = claims.get("revoked", False)
        if status in {"revoked", "disabled", "inactive"}:
            revoked = True
        if claims.get("active") is False:
            revoked = True
        return cls(
            issuer=claims.get("issuer", claims.get("iss")),
            audience=claims.get("audience", claims.get("aud")),
            subject=claims.get("subject", claims.get("sub")),
            expires_at=claims.get("expires_at", claims.get("expiry", claims.get("exp"))),
            request_id=claims.get("request_id"),
            roles=claims.get("roles", ()),
            scopes=claims.get("scopes", ()),
            revoked=revoked,
        )

    def to_auth_context(
        self,
        *,
        expected_issuer: str,
        expected_audience: str,
        now: Callable[[], datetime] = utc_now,
    ) -> AuthContext:
        expected_issuer = _claim_text(expected_issuer, "expected_issuer")
        expected_audience = _claim_text(expected_audience, "expected_audience")
        if self.issuer != expected_issuer:
            raise GatewayClaimsError("gateway issuer is not trusted")
        if self.audience != expected_audience:
            raise GatewayClaimsError("gateway audience is not trusted")
        if self.revoked:
            raise GatewayClaimsError("gateway principal is revoked")
        current = now()
        if current.tzinfo is None:
            raise GatewayClaimsError("verification clock must include a timezone")
        if self.expires_at <= current:
            raise GatewayClaimsError("gateway principal is expired")
        try:
            roles = frozenset(PrincipalRole(value) for value in self.roles)
            scopes = frozenset(Scope(value) for value in self.scopes)
        except ValueError as exc:
            raise GatewayClaimsError("gateway role or scope is not allowed") from exc
        return AuthContext(
            self.subject,
            roles=roles,
            scopes=scopes,
            request_id=self.request_id,
            issuer=self.issuer,
            audience=self.audience,
            expires_at=self.expires_at,
        )


def auth_context_from_gateway_claims(
    claims: GatewayClaims | Mapping[str, Any],
    *,
    expected_issuer: str,
    expected_audience: str,
    now: Callable[[], datetime] = utc_now,
) -> AuthContext:
    """Build an AuthContext from already-verified gateway claims."""
    typed = claims if isinstance(claims, GatewayClaims) else GatewayClaims.from_mapping(claims)
    return typed.to_auth_context(expected_issuer=expected_issuer, expected_audience=expected_audience, now=now)


def require_scope(auth: AuthContext, scope: Scope) -> None:
    if not auth.can(scope):
        raise AuthorizationError(f"missing scope: {scope.value}")


def require_role(auth: AuthContext, *roles: PrincipalRole) -> None:
    if not any(role in auth.roles for role in roles):
        allowed = ", ".join(role.value for role in roles)
        raise AuthorizationError(f"requires one of roles: {allowed}")


def require_owner(auth: AuthContext, owner_id: str) -> None:
    if auth.subject_id != owner_id and PrincipalRole.REVIEWER not in auth.roles and PrincipalRole.SERVICE not in auth.roles:
        raise AuthorizationError("resource is outside the authenticated principal's boundary")
