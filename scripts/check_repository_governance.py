"""Validate the versioned repository governance contract.

This check intentionally uses only the Python standard library so it can run
before dependency installation and fail closed when governance files drift.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


REQUIRED_FILES = (
    ".github/CODEOWNERS",
    ".github/dependabot.yml",
    ".github/workflows/codeql.yml",
    ".github/pull_request_template.md",
    ".github/ISSUE_TEMPLATE/bug_report.md",
    ".github/ISSUE_TEMPLATE/feature_request.md",
    ".github/ISSUE_TEMPLATE/config.yml",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "docs/platform/repository-governance.md",
    "scripts/check-branch-policy.sh",
    "scripts/check_branch_policy.py",
    "scripts/test-branch-policy.sh",
)


def check(root: Path) -> list[str]:
    errors: list[str] = []

    for relative_path in REQUIRED_FILES:
        path = root / relative_path
        if not path.is_file():
            errors.append(f"missing required governance file: {relative_path}")

    codeowners = root / ".github/CODEOWNERS"
    if codeowners.is_file():
        patterns = []
        for line in codeowners.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                patterns.append(stripped.split()[0])
        if "*" not in patterns:
            errors.append("CODEOWNERS must define a global fallback owner")
        scoped = {pattern for pattern in patterns if pattern != "*"}
        required_scopes = {"/apps/ios/", "/services/api/", "/services/ai/", "/packages/contracts/", "/.github/"}
        missing_scopes = sorted(required_scopes - scoped)
        if missing_scopes:
            errors.append("CODEOWNERS is missing explicit scopes: " + ", ".join(missing_scopes))

    pull_request = root / ".github/pull_request_template.md"
    if pull_request.is_file():
        text = pull_request.read_text(encoding="utf-8")
        for heading in ("## What changed", "## Requirement / decision", "## Validation", "## Privacy and security", "## Notes for reviewers"):
            if heading not in text:
                errors.append(f"PR template is missing required section: {heading}")

    issue_config = root / ".github/ISSUE_TEMPLATE/config.yml"
    if issue_config.is_file():
        text = issue_config.read_text(encoding="utf-8")
        if "blank_issues_enabled: false" not in text:
            errors.append("Issue template config must disable blank issues")
        if "security/advisories/new" not in text:
            errors.append("Issue template config must route security reports to private advisories")

    dependabot = root / ".github/dependabot.yml"
    if dependabot.is_file():
        text = dependabot.read_text(encoding="utf-8")
        for ecosystem, directory in (("github-actions", "/"), ("pip", "/services/api"), ("swift", "/apps/ios")):
            block = re.search(
                rf"package-ecosystem:\s*{re.escape(ecosystem)}\s*\n\s+directory:\s*{re.escape(directory)}\s*(?:\n|$)",
                text,
            )
            if not block:
                errors.append(f"Dependabot must monitor {ecosystem} at {directory}")

    governance = root / "docs/platform/repository-governance.md"
    if governance.is_file():
        text = governance.read_text(encoding="utf-8")
        for term in ("main", "CODEOWNERS", "Dependabot", "PHI", "weekly"):
            if term not in text:
                errors.append(f"repository governance document is missing: {term}")

    return errors


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    errors = check(root)
    if errors:
        for error in errors:
            print(f"Governance check failed: {error}", file=sys.stderr)
        return 1
    print("Repository governance checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
