#!/usr/bin/env python3
"""Provider-neutral staging service placeholder.

This process supplies only deterministic health and handoff seams for local
staging. It does not parse, persist, or log request bodies and is not a
production API or worker implementation.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import URLError
from urllib.request import Request, urlopen

_ALLOWED_ROLES = {"api", "ai-worker", "task-worker"}
_ALLOWED_MODES = {"synthetic", "provider"}


def _config(role: str) -> dict[str, str]:
    mode = os.getenv("STAGING_ADAPTER_MODE", "synthetic")
    if role not in _ALLOWED_ROLES:
        raise ValueError("unsupported staging service role")
    if mode not in _ALLOWED_MODES:
        raise ValueError("unsupported staging adapter mode")
    return {
        "service": role,
        "adapter_mode": mode,
        "startup_contract": os.getenv("STAGING_STARTUP_CONTRACT", "local"),
    }


class _Handler(BaseHTTPRequestHandler):
    server_version = "staging-runtime/1"

    def _write(self, status: int, body: dict[str, object]) -> None:
        encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802
        cfg = self.server.runtime_config  # type: ignore[attr-defined]
        if self.path == "/healthz":
            self._write(200, {"status": "ok", **cfg})
        elif self.path == "/readyz":
            self._write(200, {"status": "ready", **cfg})
        else:
            self._write(404, {"status": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/handoff":
            self._write(404, {"status": "not_found"})
            return
        # Consume and discard bounded request bytes. The placeholder never logs
        # content and never treats a request body as a queue payload.
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError:
            self._write(400, {"status": "invalid_content_length"})
            return
        if length < 0 or length > 10 * 1024 * 1024:
            self._write(413, {"status": "payload_too_large"})
            return
        if length:
            self.rfile.read(length)
        cfg = self.server.runtime_config  # type: ignore[attr-defined]
        target = os.getenv("STAGING_WORKER_URL", "synthetic://worker")
        self._write(202, {"accepted": True, "service": cfg["service"], "worker": target})

    def log_message(self, _format: str, *_args: object) -> None:
        return


def _healthcheck(port: int) -> int:
    try:
        with urlopen(Request(f"http://127.0.0.1:{port}/healthz"), timeout=2) as response:
            return 0 if response.status == 200 else 1
    except (OSError, URLError):
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", default=os.getenv("STAGING_SERVICE_ROLE", "api"))
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--healthcheck", action="store_true")
    args = parser.parse_args(argv)
    if args.healthcheck:
        return _healthcheck(args.port)
    try:
        runtime_config = _config(args.role)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    server = ThreadingHTTPServer(("0.0.0.0", args.port), _Handler)
    server.runtime_config = runtime_config  # type: ignore[attr-defined]
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
