"""Validate every action reference and each checkout's permissions boundary."""
from pathlib import Path
import re
import sys
import yaml


def check(document, text):
    if document.get("permissions") not in ({}, {"contents": "read"}):
        raise ValueError("top-level permissions must be empty or contents: read")
    for line in text.splitlines():
        if re.search(r"^\s+uses:", line) and not re.search(r"#\s+v[0-9]", line):
            raise ValueError("action references require a human-readable version comment")
    for job in document.get("jobs", {}).values():
        if "permissions" in job and job["permissions"] not in ({}, {"contents": "read"}):
            raise ValueError("jobs cannot elevate permissions")
        for step in [job, *job.get("steps", [])]:
            ref = step.get("uses")
            if ref is None:
                continue
            if not isinstance(ref, str) or not re.fullmatch(r"[^\s@]+@[a-fA-F0-9]{40}", ref):
                raise ValueError("all action and reusable-workflow references require full commit SHAs")
            if ref.startswith("actions/checkout@") and step.get("with", {}).get("persist-credentials") is not False:
                raise ValueError("each checkout must disable persisted credentials")


def main(root):
    for path in sorted((root / ".github/workflows").glob("*")):
        if path.suffix not in {".yml", ".yaml"}:
            continue
        try:
            text = path.read_text()
            check(yaml.safe_load(text), text)
        except Exception as exc:
            print(f"Workflow policy failed ({type(exc).__name__}); inspect permissions, SHA pins and checkout settings.", file=sys.stderr)
            return 1
    print("Workflow pin and permission checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]).resolve()))
