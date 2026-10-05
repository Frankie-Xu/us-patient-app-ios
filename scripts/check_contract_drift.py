#!/usr/bin/env python3
"""Check the frozen OpenAPI route inventory for intentional drift.

The contract is the source of truth.  A reviewed route-inventory snapshot is
committed next to it so a path or method change cannot pass silently.  The
checker is offline, deterministic, and emits only aggregate status data.
"""
from __future__ import annotations

import json
import os
import re
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


def _routes_from_minimal_yaml(text: str) -> list[dict[str, str]]:
    """Extract routes from the frozen contract when PyYAML is unavailable.

    This intentionally accepts only the repository's simple, quoted path
    layout. A changed or malformed YAML shape fails closed instead of being
    silently misread by a permissive parser.
    """
    path_pattern = re.compile(r'^  "([^"\\]+)":\s*$')
    method_pattern = re.compile(r'^    ([A-Za-z]+):\s*$')
    routes: list[dict[str, str]] = []
    in_paths = False
    current_path: str | None = None
    for line in text.splitlines():
        if not in_paths:
            if line == "paths:":
                in_paths = True
            continue
        if line == "components:":
            break
        path_match = path_pattern.match(line)
        if path_match:
            current_path = path_match.group(1)
            if not current_path.startswith("/"):
                raise ValueError("fallback contract path")
            continue
        method_match = method_pattern.match(line)
        if method_match and current_path:
            method = method_match.group(1).upper()
            if method in METHODS:
                routes.append({"method": method, "path": current_path})
    if not in_paths or not routes:
        raise ValueError("fallback contract shape")
    return sorted(routes, key=lambda route: (route["path"], route["method"]))


def _expected_routes(root: Path) -> list[dict[str, str]]:
    contract_path = root / "packages/contracts/openapi.yaml"
    try:
        import yaml
    except ModuleNotFoundError:
        return _routes_from_minimal_yaml(contract_path.read_text(encoding="utf-8"))
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    return _routes(contract)


def main() -> int:
    root = _root()
    try:
        expected = _expected_routes(root)
        snapshot = _snapshot(json.loads((root / "packages/contracts/contract.routes.json").read_text(encoding="utf-8")))
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
