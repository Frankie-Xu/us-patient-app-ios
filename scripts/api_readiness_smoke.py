"""Run the API health check in process without binding a port or logging payloads."""
from __future__ import annotations

import importlib
from pathlib import Path
import sys


def main(root: Path, component_dir: str) -> int:
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
                print("API readiness smoke failed: no in-process app factory is available.", file=sys.stderr)
                return 1
            from fastapi.testclient import TestClient
            response = TestClient(create_app()).get("/healthz")
            status_code = response.status_code
            body = response.json()
    except Exception as exc:
        print(f"API readiness smoke failed ({type(exc).__name__}); inspect the app locally.", file=sys.stderr)
        return 1
    if status_code != 200 or body != {"status": "ok"}:
        print("API readiness smoke failed: health endpoint did not return status=ok.", file=sys.stderr)
        return 1
    print("API readiness smoke passed (health status 200).")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]).resolve(), sys.argv[2]))
