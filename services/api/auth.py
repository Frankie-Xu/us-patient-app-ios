"""Authentication and authorization boundary.

The service accepts an already-authenticated principal. Token validation and
identity-provider integration belong in the HTTP adapter; domain methods only
consume AuthContext and enforce scopes/ownership.
"""
from __future__ import annotations

from .models import AuthContext, PrincipalRole, Scope


class AuthorizationError(PermissionError):
    pass


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
