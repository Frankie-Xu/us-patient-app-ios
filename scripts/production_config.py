"""Provider-neutral production configuration contract.

This module validates names and references, never secret values. It is suitable
for local and CI contract checks before a provider-specific adapter is selected.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
_REF_SCHEMES = ("ref://", "secret://", "parameter://", "vault://")
_DIRECT_SECRET_KEYS = {
    "ACCESS_TOKEN",
    "API_KEY",
    "API_TOKEN",
    "CLIENT_SECRET",
    "DATABASE_PASSWORD",
    "DATABASE_URL",
    "PRIVATE_KEY",
    "SECRET",
}
_ALLOWED_ENVS = {"local", "staging", "production"}


class ConfigParseError(ValueError):
    """Raised when an env file cannot be parsed safely."""


@dataclass(frozen=True)
class ConfigValidation:
    environment: str | None
    errors: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.errors


def load_env_file(path: str | Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ConfigParseError("configuration file is unavailable") from exc
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ConfigParseError(f"invalid configuration line {line_number}")
        name, value = line.split("=", 1)
        name = name.strip()
        if not _ENV_NAME.fullmatch(name):
            raise ConfigParseError(f"invalid configuration name on line {line_number}")
        if name in values:
            raise ConfigParseError(f"duplicate configuration name on line {line_number}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in (chr(34), "'"):
            value = value[1:-1]
        values[name] = value
    return values


def _require(values: Mapping[str, str], name: str, errors: list[str]) -> str | None:
    value = values.get(name, "").strip()
    if not value:
        errors.append(f"missing:{name}")
        return None
    return value


def _require_ref(values: Mapping[str, str], name: str, errors: list[str]) -> None:
    value = _require(values, name, errors)
    if value is not None and not value.startswith(_REF_SCHEMES):
        errors.append(f"reference_required:{name}")


def _require_https(values: Mapping[str, str], name: str, errors: list[str]) -> None:
    value = _require(values, name, errors)
    if value is not None and not value.startswith("https://"):
        errors.append(f"https_required:{name}")


def validate_config(values: Mapping[str, str]) -> ConfigValidation:
    errors: list[str] = []
    environment = values.get("APP_ENV", "").strip().lower()
    if environment not in _ALLOWED_ENVS:
        errors.append("invalid:APP_ENV")
        environment = None

    for name in _DIRECT_SECRET_KEYS:
        if values.get(name, "").strip():
            errors.append(f"direct_secret_forbidden:{name}")

    _require(values, "API_BASE_URL", errors)
    _require(values, "OBJECT_STORAGE_BUCKET", errors)
    _require(values, "AI_PROVIDER", errors)

    if environment in {"staging", "production"}:
        _require_https(values, "API_BASE_URL", errors)
        _require_https(values, "IDENTITY_ISSUER", errors)
        _require(values, "IDENTITY_AUDIENCE", errors)
        _require(values, "OBJECT_STORAGE_REGION", errors)
        _require(values, "QUEUE_NAME", errors)
        _require_ref(values, "DATABASE_URL_REF", errors)
        _require_ref(values, "KMS_KEY_ID_REF", errors)
        _require_ref(values, "SECRET_REF_PREFIX", errors)
        _require_https(values, "OTEL_EXPORTER_OTLP_ENDPOINT", errors)
    elif environment == "local":
        endpoint = values.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
        if endpoint and not endpoint.startswith(("http://", "https://")):
            errors.append("endpoint_scheme:OTEL_EXPORTER_OTLP_ENDPOINT")

    return ConfigValidation(environment, tuple(errors))


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate provider-neutral production configuration.")
    parser.add_argument("--env-file", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = validate_config(load_env_file(args.env_file))
    except ConfigParseError as exc:
        print(f"Configuration contract failed: {exc}")
        return 1
    if not result.valid:
        print("Configuration contract failed:")
        for error in result.errors:
            print(f"- {error}")
        return 1
    print(f"Configuration contract passed for {result.environment}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
