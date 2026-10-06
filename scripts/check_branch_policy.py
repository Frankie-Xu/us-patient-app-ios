"""Validate branch names and pull-request boundaries in CI."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


FEATURE_BRANCH = re.compile(r"^(feat|fix|docs|chore|test|refactor|ci|perf)/[a-z0-9][a-z0-9._/-]*$")
DEPENDABOT_BRANCH = re.compile(r"^dependabot/(github_actions|pip|swift)/[a-z0-9][a-z0-9._/-]*$")
PARENT_PR_REFERENCE = re.compile(r"(?im)(?:parent|base|stacked)[^\n]{0,80}(?:#\d+|/pull/\d+)")


def valid_branch(name: str) -> bool:
    return bool(FEATURE_BRANCH.fullmatch(name) or DEPENDABOT_BRANCH.fullmatch(name))


def pull_request_metadata() -> tuple[set[str], str]:
    event_path = os.environ.get("GITHUB_EVENT_PATH", "").strip()
    if not event_path:
        return set(), ""
    try:
        event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set(), ""
    pull_request = event.get("pull_request")
    if not isinstance(pull_request, dict):
        return set(), ""
    labels = {
        label.get("name", "").strip().lower()
        for label in pull_request.get("labels", [])
        if isinstance(label, dict) and isinstance(label.get("name"), str)
    }
    body = pull_request.get("body") if isinstance(pull_request.get("body"), str) else ""
    return labels, body


def main() -> int:
    head = os.environ.get("GITHUB_HEAD_REF", "").strip()
    base = os.environ.get("GITHUB_BASE_REF", "").strip()

    # Pushes to main, tags, and manual runs do not have a PR head ref.
    if not head:
        print("Branch policy skipped: no pull-request head ref is present.")
        return 0

    errors: list[str] = []
    if head in {"main", "master"}:
        errors.append("pull requests must come from a work branch")
    elif not valid_branch(head):
        errors.append(
            "head branch must use feat/, fix/, docs/, chore/, test/, refactor/, ci/, perf/, "
            "or dependabot/ naming"
        )

    if base and base == head:
        errors.append("head and base branches must be different")
    if base and base not in {"main", "master"} and not valid_branch(base):
        errors.append("stacked pull-request base branches must use the same naming policy")

    if base and base not in {"main", "master"}:
        labels, body = pull_request_metadata()
        if "stacked" not in labels:
            errors.append("stacked pull requests must carry the 'stacked' label")
        if not PARENT_PR_REFERENCE.search(body):
            errors.append("stacked pull requests must reference a parent or base PR")

    if errors:
        for error in errors:
            print(f"Branch policy failed: {error}. head={head!r} base={base!r}", file=sys.stderr)
        return 1

    print(f"Branch policy passed: head={head} base={base or 'n/a'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
