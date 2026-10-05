"""Small staging worker health process.

The checked-in API currently exposes provider-neutral local adapters, so this
process intentionally does not claim to consume production jobs. It gives the
staging composition a real, observable worker boundary while the Postgres,
S3-compatible and Redis adapters are integrated behind those protocols. It
accepts only metadata-free health requests and never logs document content.
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class HealthHandler(BaseHTTPRequestHandler):
    server_version = "patient-app-staging-worker/1"

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path not in {"/healthz", "/readyz"}:
            self._write(404, {"status": "not_found"})
            return
        if self.path == "/readyz" and not _configured_for_staging():
            self._write(503, {"status": "not_ready"})
            return
        self._write(
            200,
            {
                "status": "ok",
                "service": "worker",
                "mode": os.getenv("WORKER_MODE", "fixture"),
                "data_classification": os.getenv("STAGING_DATA_CLASSIFICATION", "deidentified"),
            },
        )

    def log_message(self, *_: object) -> None:
        # Do not log request paths or headers that could contain credentials.
        return

    def _write(self, status: int, body: dict[str, str]) -> None:
        encoded = json.dumps(body, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def _configured_for_staging() -> bool:
    classification = os.getenv("STAGING_DATA_CLASSIFICATION", "deidentified")
    if classification not in {"synthetic", "deidentified"}:
        return False
    return all(os.getenv(name, "").strip() for name in ("DATABASE_URL", "OBJECT_STORAGE_ENDPOINT", "REDIS_URL"))


def main() -> None:
    port = int(os.getenv("WORKER_PORT", "8081"))
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
