#!/usr/bin/env python3
"""Loopback-only HTTPS reverse proxy for the local staging API.

This is a developer/test helper. It intentionally binds to 127.0.0.1 only and
forwards to the HTTP API on the host. The certificate is supplied by the
caller, so the iOS Simulator can trust the generated test CA explicitly.
"""

from __future__ import annotations

import argparse
import http.client
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class ProxyHandler(BaseHTTPRequestHandler):
    server_version = "PatientAppLocalStagingTLS/1.0"

    def _forward(self) -> None:
        body_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(body_length) if body_length else None
        connection = http.client.HTTPConnection(self.server.upstream_host, self.server.upstream_port, timeout=30)
        headers = {key: value for key, value in self.headers.items() if key.lower() not in {"host", "connection"}}
        headers["Host"] = f"{self.server.upstream_host}:{self.server.upstream_port}"
        try:
            connection.request(self.command, self.path, body=body, headers=headers)
            response = connection.getresponse()
            payload = response.read()
            self.send_response(response.status, response.reason)
            for key, value in response.getheaders():
                if key.lower() not in {"connection", "transfer-encoding", "content-length"}:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except (OSError, http.client.HTTPException) as error:
            self.send_error(502, f"upstream unavailable: {error}")
        finally:
            connection.close()

    def do_GET(self) -> None:  # noqa: N802
        self._forward()

    def do_POST(self) -> None:  # noqa: N802
        self._forward()

    def do_PATCH(self) -> None:  # noqa: N802
        self._forward()

    def do_DELETE(self) -> None:  # noqa: N802
        self._forward()

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.command} {self.path} " + format % args, flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen-port", type=int, default=58443)
    parser.add_argument("--upstream-host", default="127.0.0.1")
    parser.add_argument("--upstream-port", type=int, default=58000)
    parser.add_argument("--cert", required=True)
    parser.add_argument("--key", required=True)
    args = parser.parse_args()

    server = ThreadingHTTPServer(("127.0.0.1", args.listen_port), ProxyHandler)
    server.upstream_host = args.upstream_host
    server.upstream_port = args.upstream_port
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(args.cert, args.key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    print(f"local staging HTTPS listening on https://127.0.0.1:{args.listen_port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
