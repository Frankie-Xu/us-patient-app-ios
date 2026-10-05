#!/usr/bin/env python3
"""Render a safe, aggregate Markdown summary for a release evidence manifest.

Only fixed manifest fields and aggregate counts are emitted. Metadata values,
check output, paths, request data and protected content are intentionally not
copied into the summary.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

GROUPS = ("repository", "contract", "api", "ai", "ios", "synthetic_gate")
STATUSES = {"passed", "failed", "skipped"}


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("evidence manifest is unavailable or invalid") from exc
    if not isinstance(value, dict) or value.get("manifest_schema") != "patient-app-platform/release-evidence":
        raise ValueError("unexpected evidence manifest")
    checks = value.get("checks")
    overall = value.get("overall")
    if not isinstance(checks, dict) or not isinstance(overall, dict):
        raise ValueError("incomplete evidence manifest")
    return value


def _summary(value: dict[str, Any]) -> str:
    overall = value["overall"]
    checks = value["checks"]
    statuses = [
        checks.get(group, {}).get("status")
        if isinstance(checks.get(group), dict)
        else "unknown"
        for group in GROUPS
    ]
    status = overall.get("status") if overall.get("status") in STATUSES else "unknown"
    passed = sum(item == "passed" for item in statuses)
    skipped = sum(item == "skipped" for item in statuses)
    total = len(GROUPS)
    lines = [
        "## Integration gate evidence",
        "",
        f"**Overall:** `{status}`  ",
        f"**Groups:** {passed} passed, {skipped} skipped, {total} total",
        "",
        "| Group | Status | Checks | Failed checks |",
        "| --- | --- | ---: | ---: |",
    ]
    for group, raw in ((group, checks.get(group)) for group in GROUPS):
        check = raw if isinstance(raw, dict) else {}
        items = check.get("checks", [])
        items = items if isinstance(items, list) else []
        failed = sum(1 for item in items if isinstance(item, dict) and item.get("status") == "failed")
        item_status = check.get("status") if check.get("status") in STATUSES else "unknown"
        lines.append(f"| `{group}` | `{item_status}` | {len(items)} | {failed} |")
    lines.extend([
        "",
        "The detailed redacted manifests are available in the `release-evidence-manifest` artifact.",
        "",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help=argparse.SUPPRESS)
    parser.add_argument("--output", required=True, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        rendered = _summary(_load(Path(args.input)))
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(output)
    except ValueError as exc:
        print(f"Evidence summary failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
