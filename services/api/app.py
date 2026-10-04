"""HTTP adapter for the typed application service.

The core service owns authorization, ownership, idempotency, versioning, audit,
and share semantics. This adapter only translates HTTP requests to that core.
The temporary test bearer format is:

    Bearer <subject>|<comma-separated scopes>|<comma-separated roles>

For example: ``Bearer patient-1|documents:write,facts:write|patient``.
This is a local adapter format, not production authentication or token validation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping
from urllib.parse import parse_qs, urlsplit

from .auth import AuthorizationError
from .dependencies import DependencyUnavailableError
from .models import (
    AuthContext,
    ContractError,
    JobType,
    PrincipalRole,
    ReviewStatus,
    Scope,
    SourceType,
    to_jsonable,
)
from .service import ApiService, ServiceError, ShareAccessError
from .store import IdempotencyConflictError, NotFoundError, VersionConflictError

try:  # pragma: no cover - exercised when optional HTTP dependencies are installed
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
except ImportError:  # pragma: no cover - default dependency-light environment
    FastAPI = None  # type: ignore[assignment]
    Request = Any  # type: ignore[assignment,misc]
    JSONResponse = None  # type: ignore[assignment]


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    body: Any
    headers: Mapping[str, str] = ()


class RequestValidationError(ValueError):
    pass


class MissingBearerError(PermissionError):
    pass


def _error_response(status_code: int, code: str, detail: str) -> HttpResponse:
    return HttpResponse(status_code, {"code": code, "detail": detail})


def _header(headers: Mapping[str, str], name: str) -> str | None:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return None


def _required(data: Mapping[str, Any], *fields: str) -> None:
    missing = [field for field in fields if field not in data]
    if missing:
        raise RequestValidationError(f"missing required field(s): {', '.join(missing)}")


def _reject_extra(data: Mapping[str, Any], *fields: str) -> None:
    extra = sorted(set(data) - set(fields))
    if extra:
        raise RequestValidationError(f"unknown field(s): {', '.join(extra)}")


def _as_datetime(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise RequestValidationError(f"{field} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RequestValidationError(f"{field} must be an ISO-8601 string") from exc
    if parsed.tzinfo is None:
        raise RequestValidationError(f"{field} must include a timezone")
    return parsed


def _temporary_auth(headers: Mapping[str, str]) -> AuthContext:
    raw = _header(headers, "Authorization")
    if not raw or not raw.startswith("Bearer "):
        raise MissingBearerError("Bearer authorization is required")
    encoded = raw[len("Bearer "):].strip()
    parts = encoded.split("|")
    if len(parts) != 3 or not parts[0].strip():
        raise MissingBearerError("temporary bearer format is subject|scopes|roles")
    subject, scopes_text, roles_text = (part.strip() for part in parts)
    try:
        scopes = frozenset(Scope(item) for item in scopes_text.split(",") if item)
        roles = frozenset(PrincipalRole(item) for item in roles_text.split(",") if item)
    except ValueError as exc:
        raise MissingBearerError("temporary bearer contains an unknown scope or role") from exc
    request_id = _header(headers, "X-Request-Id") or "http-request"
    return AuthContext(subject, roles=roles, scopes=scopes, request_id=request_id)


class ApiHttpAdapter:
    """Framework-neutral HTTP adapter used by FastAPI and local integration tests."""

    def __init__(self, service: ApiService | None = None) -> None:
        self.service = service or ApiService()

    def handle(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: Any = None,
    ) -> HttpResponse:
        method = method.upper()
        headers = headers or {}
        route = urlsplit(path).path.rstrip("/") or "/"
        try:
            if method == "GET" and route == "/healthz":
                return HttpResponse(200, {"status": "ok"})
            if method == "GET" and route == "/readyz":
                readiness = self.service.readiness()
                if readiness["status"] == "ready":
                    return HttpResponse(200, readiness)
                return HttpResponse(503, {**readiness, "code": "DEPENDENCY_UNAVAILABLE", "detail": "one or more dependencies are unavailable"})
            if method == "GET" and route == "/v1/shared" or route.startswith("/v1/shared/") and method == "GET":
                token = route.split("/", 3)[3] if route.count("/") >= 3 else ""
                share, resource = self.service.access_share(token)
                return HttpResponse(200, {"share": to_jsonable(share), "resource": to_jsonable(resource)})

            auth = _temporary_auth(headers)
            if method == "POST" and route == "/v1/documents":
                data = self._body(body)
                _required(data, "filename", "media_type", "size_bytes", "sha256")
                _reject_extra(data, "filename", "media_type", "size_bytes", "sha256")
                document = self.service.create_document(
                    auth,
                    filename=self._string(data, "filename"),
                    media_type=self._string(data, "media_type"),
                    size_bytes=self._non_negative_int(data, "size_bytes"),
                    sha256=self._string(data, "sha256"),
                    idempotency_key=self._idempotency(headers),
                )
                return HttpResponse(201, to_jsonable(document))
            if method == "GET" and route == "/v1/documents":
                return HttpResponse(200, [to_jsonable(item) for item in self.service.list_documents(auth)])
            if method == "GET" and route.startswith("/v1/documents/") and route.count("/") == 3:
                return HttpResponse(200, to_jsonable(self.service.get_document(auth, route.rsplit("/", 1)[1])))
            if method == "POST" and route.startswith("/v1/documents/") and route.endswith("/processing-jobs"):
                data = self._body(body)
                _required(data, "job_type")
                _reject_extra(data, "job_type")
                job = self.service.enqueue_processing(
                    auth,
                    document_id=route.split("/")[3],
                    job_type=JobType(self._string(data, "job_type")),
                    idempotency_key=self._idempotency(headers),
                )
                return HttpResponse(202, to_jsonable(job))
            if method == "POST" and route == "/v1/topics":
                data = self._body(body)
                _required(data, "name")
                _reject_extra(data, "name")
                topic = self.service.create_topic(
                    auth,
                    name=self._string(data, "name"),
                    idempotency_key=self._idempotency(headers),
                )
                return HttpResponse(201, to_jsonable(topic))
            if method == "POST" and route == "/v1/visits":
                data = self._body(body)
                _required(data, "title")
                _reject_extra(data, "title", "starts_at", "topic_ids")
                starts_at = None if data.get("starts_at") is None else _as_datetime(data["starts_at"], "starts_at")
                visit = self.service.create_visit(
                    auth,
                    title=self._string(data, "title"),
                    starts_at=starts_at,
                    topic_ids=self._string_list(data, "topic_ids"),
                    idempotency_key=self._idempotency(headers),
                )
                return HttpResponse(201, to_jsonable(visit))
            if method == "POST" and route == "/v1/tasks":
                data = self._body(body)
                _required(data, "title")
                _reject_extra(data, "title", "visit_id", "due_at")
                due_at = None if data.get("due_at") is None else _as_datetime(data["due_at"], "due_at")
                task = self.service.create_task(
                    auth,
                    title=self._string(data, "title"),
                    visit_id=self._optional_string(data, "visit_id"),
                    due_at=due_at,
                    idempotency_key=self._idempotency(headers),
                )
                return HttpResponse(201, to_jsonable(task))
            if method == "POST" and route == "/v1/facts":
                data = self._body(body)
                _required(data, "label", "value", "source_ref", "source_type", "confidence")
                _reject_extra(data, "label", "value", "source_ref", "source_type", "confidence", "document_id", "topic_id")
                fact = self.service.create_fact(
                    auth,
                    label=self._string(data, "label"),
                    value=self._string(data, "value"),
                    source_ref=self._string(data, "source_ref"),
                    source_type=SourceType(self._string(data, "source_type")),
                    confidence=self._number(data, "confidence"),
                    document_id=data.get("document_id"),
                    topic_id=data.get("topic_id"),
                    idempotency_key=self._idempotency(headers),
                )
                return HttpResponse(201, to_jsonable(fact))
            if method == "GET" and route == "/v1/facts":
                return HttpResponse(200, [to_jsonable(item) for item in self.service.list_facts(auth)])
            if method == "POST" and route.startswith("/v1/facts/") and route.endswith("/review"):
                data = self._body(body)
                _required(data, "review_status")
                _reject_extra(data, "review_status")
                version = _header(headers, "If-Match-Version")
                if version is None:
                    raise RequestValidationError("If-Match-Version is required")
                try:
                    expected_version = int(version)
                except ValueError as exc:
                    raise RequestValidationError("If-Match-Version must be an integer") from exc
                fact = self.service.review_fact(
                    auth,
                    route.split("/")[3],
                    review_status=ReviewStatus(self._string(data, "review_status")),
                    expected_version=expected_version,
                )
                return HttpResponse(200, to_jsonable(fact))
            if method == "POST" and route == "/v1/shares":
                data = self._body(body)
                _required(data, "resource_type", "resource_id", "resource_version", "expires_at")
                _reject_extra(data, "resource_type", "resource_id", "resource_version", "expires_at")
                share, token = self.service.create_share(
                    auth,
                    resource_type=self._string(data, "resource_type"),
                    resource_id=self._string(data, "resource_id"),
                    resource_version=self._positive_int(data, "resource_version"),
                    expires_at=_as_datetime(data["expires_at"], "expires_at"),
                    idempotency_key=self._idempotency(headers),
                )
                return HttpResponse(201, {"share": to_jsonable(share), "token": token})
            if method == "POST" and route.startswith("/v1/shares/") and route.endswith("/revoke"):
                share = self.service.revoke_share(auth, route.split("/")[3])
                return HttpResponse(200, to_jsonable(share))
            if method == "GET" and route == "/v1/audit-events":
                query = parse_qs(urlsplit(path).query)
                resource_id = query.get("resource_id", [None])[0]
                return HttpResponse(200, [to_jsonable(event) for event in self.service.list_audit(auth, resource_id=resource_id)])
            return HttpResponse(404, {"detail": "route not found"})
        except MissingBearerError as exc:
            return _error_response(401, "AUTHENTICATION_REQUIRED", str(exc))
        except AuthorizationError as exc:
            return _error_response(403, "FORBIDDEN", str(exc))
        except DependencyUnavailableError as exc:
            return _error_response(503, "DEPENDENCY_UNAVAILABLE", str(exc))
        except IdempotencyConflictError as exc:
            return _error_response(409, "IDEMPOTENCY_CONFLICT", str(exc))
        except VersionConflictError as exc:
            return _error_response(409, "VERSION_CONFLICT", str(exc))
        except ShareAccessError as exc:
            message = str(exc)
            if "expired" in message:
                return _error_response(410, "SHARE_EXPIRED", message)
            if "revoked" in message:
                return _error_response(410, "SHARE_REVOKED", message)
            return _error_response(404, "SHARE_NOT_FOUND", "share token is invalid")
        except NotFoundError as exc:
            return _error_response(404, "NOT_FOUND", str(exc))
        except (ContractError, RequestValidationError, ValueError, TypeError) as exc:
            return _error_response(422, "VALIDATION_ERROR", str(exc))
        except ServiceError as exc:
            return _error_response(422, "SERVICE_ERROR", str(exc))
        except Exception:
            # Never reflect unexpected exception text: it may contain request or PHI data.
            return _error_response(500, "INTERNAL_ERROR", "internal server error")

    @staticmethod
    def _body(body: Any) -> dict[str, Any]:
        if not isinstance(body, dict):
            raise RequestValidationError("JSON object body is required")
        return body

    @staticmethod
    def _string(data: Mapping[str, Any], field: str) -> str:
        value = data[field]
        if not isinstance(value, str) or not value.strip():
            raise RequestValidationError(f"{field} must be a non-empty string")
        return value

    @staticmethod
    def _optional_string(data: Mapping[str, Any], field: str) -> str | None:
        if field not in data or data[field] is None:
            return None
        return ApiHttpAdapter._string(data, field)

    @staticmethod
    def _string_list(data: Mapping[str, Any], field: str) -> tuple[str, ...]:
        value = data.get(field, [])
        if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
            raise RequestValidationError(f"{field} must be an array of non-empty strings")
        return tuple(value)

    @staticmethod
    def _number(data: Mapping[str, Any], field: str) -> float:
        value = data[field]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise RequestValidationError(f"{field} must be a number")
        return float(value)

    @classmethod
    def _non_negative_int(cls, data: Mapping[str, Any], field: str) -> int:
        value = data[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise RequestValidationError(f"{field} must be a non-negative integer")
        return value

    @classmethod
    def _positive_int(cls, data: Mapping[str, Any], field: str) -> int:
        value = cls._non_negative_int(data, field)
        if value < 1:
            raise RequestValidationError(f"{field} must be >= 1")
        return value

    @staticmethod
    def _idempotency(headers: Mapping[str, str]) -> str:
        value = _header(headers, "Idempotency-Key")
        if not value:
            raise RequestValidationError("Idempotency-Key is required")
        return value


def create_app(service: ApiService | None = None):
    """Create the optional FastAPI adapter using the temporary bearer parser."""
    if FastAPI is None:
        raise RuntimeError("FastAPI is optional; install services/api dependencies to run HTTP routes")
    adapter = ApiHttpAdapter(service)
    api = FastAPI(title="US Patient App API", version="0.2.0", docs_url="/docs")

    @api.api_route("/{path:path}", methods=["GET", "POST"], include_in_schema=False)
    async def invoke(path: str, request: Request):
        try:
            body = await request.json() if request.method != "GET" else None
        except Exception:
            body = None
        request_path = "/" + path
        if request.url.query:
            request_path += f"?{request.url.query}"
        result = adapter.handle(request.method, request_path, headers=request.headers, body=body)
        return JSONResponse(status_code=result.status_code, content=result.body, headers=dict(result.headers))

    return api


app = None
if FastAPI is not None:  # keep import side effects small for dependency-light tests
    app = create_app()
