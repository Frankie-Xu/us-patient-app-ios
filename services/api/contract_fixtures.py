"""Typed synthetic fixtures and fail-closed checks for the frozen OpenAPI contract.

The mobile client will eventually generate models from ``packages/contracts``.
Until that generator is selected, these small dataclasses keep the request and
response examples typed while the tests verify that the checked-in OpenAPI
shapes have not drifted.  No fixture contains clinical data.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Mapping


class ContractDriftError(ValueError):
    """Raised when a frozen OpenAPI schema no longer matches its snapshot."""


class ContractValidationError(ValueError):
    """Raised when a request or response has missing or unknown fields."""


@dataclass(frozen=True)
class SchemaShape:
    required: frozenset[str]
    properties: frozenset[str]
    additional_properties: bool


# These are the shapes consumed by the visit-pack, account-history and sharing
# clients.  Keeping the snapshot explicit makes a contract edit fail closed in
# CI instead of silently broadening a decoder.
FROZEN_SHAPES: dict[str, SchemaShape] = {
    "TopicCreate": SchemaShape(frozenset({"name"}), frozenset({"name"}), False),
    "Topic": SchemaShape(
        frozenset({"name", "id", "owner_id", "version", "created_at", "updated_at"}),
        frozenset({"name", "id", "owner_id", "version", "created_at", "updated_at"}),
        False,
    ),
    "VisitCreate": SchemaShape(
        frozenset({"title"}), frozenset({"title", "starts_at", "topic_ids"}), False
    ),
    "Visit": SchemaShape(
        frozenset({"title", "id", "owner_id", "version", "created_at", "updated_at"}),
        frozenset({"title", "starts_at", "topic_ids", "id", "owner_id", "version", "created_at", "updated_at"}),
        False,
    ),
    "TaskCreate": SchemaShape(
        frozenset({"title"}), frozenset({"title", "visit_id", "due_at"}), False
    ),
    "Task": SchemaShape(
        frozenset({"title", "id", "owner_id", "status", "version", "created_at", "updated_at"}),
        frozenset({"title", "visit_id", "due_at", "id", "owner_id", "status", "version", "created_at", "updated_at"}),
        False,
    ),
    "ShareCreate": SchemaShape(
        frozenset({"resource_type", "resource_id", "resource_version", "expires_at"}),
        frozenset({"resource_type", "resource_id", "resource_version", "expires_at"}),
        False,
    ),
    "ShareVersion": SchemaShape(
        frozenset({"id", "owner_id", "resource_type", "resource_id", "resource_version", "expires_at", "status", "created_at"}),
        frozenset({"id", "owner_id", "resource_type", "resource_id", "resource_version", "expires_at", "status", "revoked_at", "created_at"}),
        False,
    ),
    "ShareReceipt": SchemaShape(frozenset({"share", "token"}), frozenset({"share", "token"}), False),
    "SharedResource": SchemaShape(frozenset({"share", "resource"}), frozenset({"share", "resource"}), False),
}


def _openapi_path() -> Path:
    return Path(__file__).parents[2] / "packages" / "contracts" / "openapi.yaml"


def parse_openapi_shapes(text: str) -> dict[str, SchemaShape]:
    """Parse the object schema field sets without adding a YAML dependency.

    The repository intentionally runs dependency-free contract tests.  This
    parser reads only the stable OpenAPI object constructs used by the frozen
    schemas (``required``, ``properties`` and ``additionalProperties``).
    """
    lines = text.splitlines()
    in_schemas = False
    current: str | None = None
    required: set[str] = set()
    properties: set[str] = set()
    additional_properties = True
    mode: str | None = None
    parsed: dict[str, SchemaShape] = {}

    def finish() -> None:
        nonlocal current, required, properties, additional_properties, mode
        if current is not None:
            parsed[current] = SchemaShape(
                frozenset(required), frozenset(properties), additional_properties
            )
        current = None
        required = set()
        properties = set()
        additional_properties = True
        mode = None

    for line in lines:
        if line == "  schemas:":
            in_schemas = True
            continue
        if not in_schemas:
            continue
        schema_match = re.fullmatch(r"    ([A-Za-z][A-Za-z0-9_-]*):", line)
        if schema_match:
            finish()
            current = schema_match.group(1)
            continue
        if current is None:
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if indent <= 4 and stripped and not stripped.startswith("#"):
            finish()
            in_schemas = False
            continue
        if indent == 6 and stripped == "required:":
            mode = "required"
            continue
        if indent == 6 and stripped == "properties:":
            mode = "properties"
            continue
        if indent == 6 and stripped.startswith("additionalProperties:"):
            additional_properties = stripped.split(":", 1)[1].strip().lower() != "false"
            mode = None
            continue
        if mode == "required" and indent == 6 and stripped.startswith("- "):
            required.add(stripped[2:].strip().strip("'\""))
            continue
        if mode == "properties" and indent == 8:
            property_match = re.fullmatch(r"([A-Za-z][A-Za-z0-9_-]*):", stripped)
            if property_match:
                properties.add(property_match.group(1))
    finish()
    return parsed


def assert_frozen_openapi_contract(path: Path | None = None) -> dict[str, SchemaShape]:
    """Return parsed shapes or fail closed when the frozen snapshot drifts."""
    source = (path or _openapi_path()).read_text(encoding="utf-8")
    actual = parse_openapi_shapes(source)
    for name, expected in FROZEN_SHAPES.items():
        observed = actual.get(name)
        if observed is None:
            raise ContractDriftError(f"OpenAPI schema missing: {name}")
        if observed != expected:
            raise ContractDriftError(
                f"OpenAPI schema drift for {name}: expected {expected}, observed {observed}"
            )
    return actual


def validate_payload(schema_name: str, payload: Mapping[str, Any], *, path: Path | None = None) -> None:
    """Reject unknown and missing fields against the frozen OpenAPI shape."""
    if not isinstance(payload, Mapping):
        raise ContractValidationError(f"{schema_name} must be an object")
    shapes = assert_frozen_openapi_contract(path)
    shape = shapes.get(schema_name)
    if shape is None:
        raise ContractValidationError(f"unsupported contract schema: {schema_name}")
    unknown = sorted(set(payload) - shape.properties)
    if unknown:
        raise ContractValidationError(f"{schema_name} has unknown field(s): {', '.join(unknown)}")
    missing = sorted(shape.required - set(payload))
    if missing:
        raise ContractValidationError(f"{schema_name} is missing required field(s): {', '.join(missing)}")


@dataclass(frozen=True)
class TopicCreateFixture:
    name: str

    def payload(self) -> dict[str, Any]:
        payload = {"name": self.name}
        validate_payload("TopicCreate", payload)
        return payload


@dataclass(frozen=True)
class VisitCreateFixture:
    title: str
    starts_at: str | None = None
    topic_ids: tuple[str, ...] = ()

    def payload(self) -> dict[str, Any]:
        payload = {"title": self.title, "starts_at": self.starts_at, "topic_ids": list(self.topic_ids)}
        validate_payload("VisitCreate", payload)
        return payload


@dataclass(frozen=True)
class TaskCreateFixture:
    title: str
    visit_id: str | None = None
    due_at: str | None = None

    def payload(self) -> dict[str, Any]:
        payload = {"title": self.title, "visit_id": self.visit_id, "due_at": self.due_at}
        validate_payload("TaskCreate", payload)
        return payload


@dataclass(frozen=True)
class ShareCreateFixture:
    resource_type: str
    resource_id: str
    resource_version: int
    expires_at: str

    def payload(self) -> dict[str, Any]:
        payload = {
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "resource_version": self.resource_version,
            "expires_at": self.expires_at,
        }
        validate_payload("ShareCreate", payload)
        return payload


@dataclass(frozen=True)
class TopicResponseFixture:
    name: str
    id: str
    owner_id: str
    version: int
    created_at: str
    updated_at: str

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "TopicResponseFixture":
        validate_response("Topic", payload)
        return cls(
            name=payload["name"],
            id=payload["id"],
            owner_id=payload["owner_id"],
            version=payload["version"],
            created_at=payload["created_at"],
            updated_at=payload["updated_at"],
        )


@dataclass(frozen=True)
class VisitResponseFixture:
    title: str
    starts_at: str | None
    topic_ids: tuple[str, ...]
    id: str
    owner_id: str
    version: int
    created_at: str
    updated_at: str

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "VisitResponseFixture":
        validate_response("Visit", payload)
        return cls(
            title=payload["title"],
            starts_at=payload["starts_at"],
            topic_ids=tuple(payload["topic_ids"]),
            id=payload["id"],
            owner_id=payload["owner_id"],
            version=payload["version"],
            created_at=payload["created_at"],
            updated_at=payload["updated_at"],
        )


@dataclass(frozen=True)
class TaskResponseFixture:
    title: str
    visit_id: str | None
    due_at: str | None
    id: str
    owner_id: str
    status: str
    version: int
    created_at: str
    updated_at: str

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "TaskResponseFixture":
        validate_response("Task", payload)
        return cls(
            title=payload["title"],
            visit_id=payload["visit_id"],
            due_at=payload["due_at"],
            id=payload["id"],
            owner_id=payload["owner_id"],
            status=payload["status"],
            version=payload["version"],
            created_at=payload["created_at"],
            updated_at=payload["updated_at"],
        )


@dataclass(frozen=True)
class ShareVersionResponseFixture:
    id: str
    owner_id: str
    resource_type: str
    resource_id: str
    resource_version: int
    expires_at: str
    status: str
    revoked_at: str | None
    created_at: str

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ShareVersionResponseFixture":
        validate_response("ShareVersion", payload)
        return cls(
            id=payload["id"],
            owner_id=payload["owner_id"],
            resource_type=payload["resource_type"],
            resource_id=payload["resource_id"],
            resource_version=payload["resource_version"],
            expires_at=payload["expires_at"],
            status=payload["status"],
            revoked_at=payload["revoked_at"],
            created_at=payload["created_at"],
        )


@dataclass(frozen=True)
class ShareReceiptResponseFixture:
    share: ShareVersionResponseFixture
    token: str

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ShareReceiptResponseFixture":
        validate_response("ShareReceipt", payload)
        return cls(
            share=ShareVersionResponseFixture.from_payload(payload["share"]),
            token=payload["token"],
        )


@dataclass(frozen=True)
class SharedResourceResponseFixture:
    share: ShareVersionResponseFixture
    resource: Mapping[str, Any]

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "SharedResourceResponseFixture":
        validate_response("SharedResource", payload)
        return cls(
            share=ShareVersionResponseFixture.from_payload(payload["share"]),
            resource=dict(payload["resource"]),
        )


def validate_response(schema_name: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a response object and return a shallow copy for typed callers."""
    validate_payload(schema_name, payload)
    return dict(payload)
