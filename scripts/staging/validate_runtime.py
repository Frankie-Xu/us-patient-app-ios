#!/usr/bin/env python3
"""Validate the rendered staging compose contract without starting services."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


_EXPECTED_SERVICES = {
    "postgres",
    "minio",
    "migration",
    "queue-init",
    "object-storage-init",
    "api",
    "ai-worker",
    "task-worker",
}
_COMPLETED = "service_completed_successfully"
_HEALTHY = "service_healthy"


def _fail(message: str) -> None:
    raise SystemExit(f"staging runtime validation failed: {message}")


def _env(service: dict[str, Any]) -> dict[str, str]:
    values = service.get("environment", {})
    if isinstance(values, list):
        result: dict[str, str] = {}
        for item in values:
            if "=" in item:
                key, value = item.split("=", 1)
                result[key] = value
        return result
    return {str(key): str(value) for key, value in values.items()}


def _depends(service: dict[str, Any]) -> dict[str, dict[str, Any]]:
    values = service.get("depends_on", {})
    if not isinstance(values, dict):
        _fail("depends_on must be a condition map")
    return values


def _require_condition(services: dict[str, Any], service_name: str, dependency: str, condition: str) -> None:
    service = services.get(service_name)
    if not isinstance(service, dict):
        _fail(f"missing service {service_name}")
    dependency_config = _depends(service).get(dependency)
    if not isinstance(dependency_config, dict) or dependency_config.get("condition") != condition:
        _fail(f"{service_name} must wait for {dependency} with {condition}")


def main(argv: list[str] | None = None) -> int:
    if len(argv or sys.argv) != 2:
        _fail("usage: validate_runtime.py <rendered-compose-json>")
    config_path = Path((argv or sys.argv)[1])
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _fail(f"cannot read rendered compose config: {exc}")
    services = config.get("services")
    if not isinstance(services, dict):
        _fail("rendered config has no services")
    if set(services) != _EXPECTED_SERVICES:
        _fail(f"service graph mismatch: {sorted(services)}")

    for dependency in ("postgres", "minio"):
        if not services[dependency].get("healthcheck"):
            _fail(f"{dependency} must have a healthcheck")
    for service_name in ("api", "ai-worker", "task-worker"):
        if not services[service_name].get("healthcheck"):
            _fail(f"{service_name} must have a healthcheck")
        _require_condition(services, service_name, "migration", _COMPLETED)
        _require_condition(services, service_name, "queue-init", _COMPLETED)
        _require_condition(services, service_name, "object-storage-init", _COMPLETED)

    _require_condition(services, "migration", "postgres", _HEALTHY)
    _require_condition(services, "queue-init", "migration", _COMPLETED)
    _require_condition(services, "object-storage-init", "minio", _HEALTHY)

    api_env = _env(services["api"])
    if api_env.get("STAGING_ADAPTER_MODE") != "synthetic":
        _fail("api must default to the synthetic adapter")
    if api_env.get("STAGING_OCR_PROVIDER") != "deterministic":
        _fail("api must default to deterministic OCR")
    if api_env.get("STAGING_EXTRACTION_PROVIDER") != "deterministic":
        _fail("api must default to deterministic extraction")
    if api_env.get("STAGING_WORKER_URL") != "http://ai-worker:8090":
        _fail("api worker handoff URL is not internal and deterministic")
    if api_env.get("STAGING_TASK_WORKER_URL") != "http://task-worker:8091":
        _fail("api task worker URL is not internal and deterministic")

    for service_name in ("ai-worker", "task-worker"):
        worker_env = _env(services[service_name])
        if worker_env.get("STAGING_STARTUP_CONTRACT") != "compose":
            _fail(f"{service_name} missing compose startup contract")
        if worker_env.get("STAGING_QUEUE_MODE") != "database":
            _fail(f"{service_name} must use the database queue seam")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
