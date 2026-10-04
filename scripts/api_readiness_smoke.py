"""Run the API health check in process without binding a port or logging payloads."""
from __future__ import annotations

import importlib
import json
from pathlib import Path
import sys
from typing import Any


def _write_result(path: str, status: str, **fields: Any) -> None:
    if not path:
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": 1, "check": "api_readiness", "status": status, **fields}
    output.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


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
            response = adapter_type().handle("GET", "/healthz")
            status_code = response.status_code
            body = response.body
        else:
            create_app = getattr(module, "create_app", None)
            if create_app is None:
                _write_result(artifact_path, "failed", reason="app_factory_absent")
                print("API readiness smoke failed: no in-process app factory is available.", file=sys.stderr)
                return 1
            from fastapi.testclient import TestClient
            response = TestClient(create_app()).get("/healthz")
            status_code = response.status_code
            body = response.json()
    except Exception as exc:
        _write_result(artifact_path, "failed", error_type=type(exc).__name__)
        print(f"API readiness smoke failed ({type(exc).__name__}); inspect the app locally.", file=sys.stderr)
        return 1
    if status_code != 200 or body != {"status": "ok"}:
        _write_result(artifact_path, "failed", health_status=status_code, response_shape="unexpected")
        print("API readiness smoke failed: health endpoint did not return status=ok.", file=sys.stderr)
        return 1
    _write_result(artifact_path, "passed", health_status=200, response_shape="status_ok")
    print("API readiness smoke passed (health status 200).")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]).resolve(), sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else ""))
