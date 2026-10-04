"""Run the API health check in process without binding a port or logging payloads."""
from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any


ROUTE_FAMILIES = ("topics", "visits", "tasks")
ROUTE_AUTH = {"Authorization": "Bearer synthetic-ci|visits:write,tasks:write|patient"}


@dataclass(frozen=True)
class RouteSmokeRequest:
    body: dict[str, Any]
    idempotency_key: str


ROUTE_SMOKE_REQUESTS = {
    "topics": RouteSmokeRequest({"name": "synthetic-topic"}, "ci-topic-001"),
    "visits": RouteSmokeRequest({"title": "synthetic-visit", "starts_at": None, "topic_ids": []}, "ci-visit-001"),
    "tasks": RouteSmokeRequest({"title": "synthetic-task", "visit_id": None, "due_at": None}, "ci-task-001"),
}


def _write_result(path: str, status: str, **fields: Any) -> None:
    if not path:
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": 1, "check": "api_readiness", "status": status, **fields}
    output.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _route_statuses(adapter: Any) -> dict[str, int]:
    statuses: dict[str, int] = {}
    for family in ROUTE_FAMILIES:
        request = ROUTE_SMOKE_REQUESTS[family]
        headers = {**ROUTE_AUTH, "Idempotency-Key": request.idempotency_key}
        response = adapter.handle("POST", f"/v1/{family}", headers=headers, body=request.body)
        statuses[family] = int(response.status_code)
    return statuses


def _route_statuses_from_client(client: Any) -> dict[str, int]:
    return {
        family: int(
            client.post(
                f"/v1/{family}",
                headers={**ROUTE_AUTH, "Idempotency-Key": ROUTE_SMOKE_REQUESTS[family].idempotency_key},
                json=ROUTE_SMOKE_REQUESTS[family].body,
            ).status_code
        )
        for family in ROUTE_FAMILIES
    }


def main(root: Path, component_dir: str, artifact_path: str = "") -> int:
    component_path = root / component_dir
    if not component_path.is_dir() or not (component_path / "app.py").is_file():
        _write_result(artifact_path, "skipped", reason="app_adapter_absent")
        print(f"Skipping API readiness smoke: {component_dir} app adapter is not present yet.")
        return 0

    sys.path.insert(0, str(root))
    try:
        module = importlib.import_module("services.api.app")
        adapter_type = getattr(module, "ApiHttpAdapter", None)
        if adapter_type is not None:
            adapter = adapter_type()
            response = adapter.handle("GET", "/healthz")
            status_code = response.status_code
            body = response.body
            route_statuses = _route_statuses(adapter)
        else:
            create_app = getattr(module, "create_app", None)
            if create_app is None:
                _write_result(artifact_path, "failed", reason="app_factory_absent")
                print("API readiness smoke failed: no in-process app factory is available.", file=sys.stderr)
                return 1
            from fastapi.testclient import TestClient
            with TestClient(create_app()) as client:
                response = client.get("/healthz")
                route_statuses = _route_statuses_from_client(client)
            status_code = response.status_code
            body = response.json()
    except Exception as exc:
        _write_result(artifact_path, "failed", error_type=type(exc).__name__)
        print(f"API readiness smoke failed ({type(exc).__name__}); inspect the app locally.", file=sys.stderr)
        return 1
    if status_code != 200 or body != {"status": "ok"}:
        _write_result(artifact_path, "failed", health_status=status_code, response_shape="unexpected", route_statuses=route_statuses if "route_statuses" in locals() else {})
        print("API readiness smoke failed: health endpoint did not return status=ok.", file=sys.stderr)
        return 1
    if any(route_statuses[family] != 201 for family in ROUTE_FAMILIES):
        _write_result(artifact_path, "failed", health_status=200, response_shape="route_status_unexpected", route_statuses=route_statuses)
        print("API readiness smoke failed: topics/visits/tasks route smoke did not return 201.", file=sys.stderr)
        return 1
    _write_result(artifact_path, "passed", health_status=200, response_shape="status_ok", route_statuses=route_statuses)
    route_summary = ",".join(f"{family}:{route_statuses[family]}" for family in ROUTE_FAMILIES)
    print(f"API readiness smoke passed (health status 200; topics/visits/tasks routes={route_summary}).")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]).resolve(), sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else ""))
