"""Validate branch names and pull-request boundaries in CI."""

from __future__ import annotations

import os
import re
import sys


FEATURE_BRANCH = re.compile(r"^(feat|fix|docs|chore|test|refactor|ci|perf)/[a-z0-9][a-z0-9._/-]*$")
DEPENDABOT_BRANCH = re.compile(r"^dependabot/(github_actions|pip|swift)/[a-z0-9][a-z0-9._/-]*$")


def valid_branch(name: str) -> bool:
    return bool(FEATURE_BRANCH.fullmatch(name) or DEPENDABOT_BRANCH.fullmatch(name))


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

    if errors:
        for error in errors:
            print(f"Branch policy failed: {error}. head={head!r} base={base!r}", file=sys.stderr)
        return 1

    print(f"Branch policy passed: head={head} base={base or 'n/a'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
