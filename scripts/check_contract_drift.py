#!/usr/bin/env python3
"""Check the frozen OpenAPI route inventory for intentional drift.

The contract is the source of truth.  A reviewed route-inventory snapshot is
committed next to it so a path or method change cannot pass silently.  The
checker is offline, deterministic, and emits only aggregate status data.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

SCHEMA = "patient-app-platform/openapi-route-inventory"
VERSION = "1.0.0"
METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD", "TRACE"}


def _root() -> Path:
    return Path(os.environ.get("VALIDATION_ROOT", Path(__file__).resolve().parents[1])).resolve()


def _routes(document: Any) -> list[dict[str, str]]:
    if not isinstance(document, dict) or not isinstance(document.get("paths"), dict):
        raise ValueError("contract shape")
    routes: list[dict[str, str]] = []
    for path, item in document["paths"].items():
        if not isinstance(path, str) or not path.startswith("/") or not isinstance(item, dict):
            raise ValueError("contract route")
        for method, operation in item.items():
            method_upper = str(method).upper()
            if method_upper not in METHODS:
                continue
            if not isinstance(operation, dict):
                raise ValueError("contract operation")
            routes.append({"method": method_upper, "path": path})
    if not routes:
        raise ValueError("empty contract")
    return sorted(routes, key=lambda route: (route["path"], route["method"]))


def _snapshot(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, dict) or set(value) != {"schema", "version", "routes"}:
        raise ValueError("snapshot envelope")
    if value["schema"] != SCHEMA or value["version"] != VERSION:
        raise ValueError("snapshot version")
    routes = value["routes"]
    if not isinstance(routes, list) or any(
        not isinstance(item, dict) or set(item) != {"method", "path"}
        or item["method"] not in METHODS
        or not isinstance(item["path"], str)
        or not item["path"].startswith("/")
        for item in routes
    ):
        raise ValueError("snapshot route")
    normalized = sorted(routes, key=lambda route: (route["path"], route["method"]))
    if normalized != routes or len({(item["method"], item["path"]) for item in routes}) != len(routes):
        raise ValueError("snapshot ordering")
    return routes


def main() -> int:
    root = _root()
    try:
        import yaml

        contract = yaml.safe_load((root / "packages/contracts/openapi.yaml").read_text(encoding="utf-8"))
        expected = _routes(contract)
        snapshot = _snapshot(json.loads((root / "packages/contracts/openapi.routes.json").read_text(encoding="utf-8")))
    except Exception:
        print("OpenAPI contract drift check failed; inspect the contract inventory locally.", file=sys.stderr)
        return 1
    if expected != snapshot:
        print("OpenAPI contract drift detected; update the reviewed route inventory.", file=sys.stderr)
        return 1
    print(f"OpenAPI contract drift check passed ({len(expected)} routes).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
