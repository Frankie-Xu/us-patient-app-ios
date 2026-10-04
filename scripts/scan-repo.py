#!/usr/bin/env python3
"""Scan repository text for policy patterns without external CLI dependencies."""

from __future__ import annotations

import argparse
import fnmatch
import os
import re
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--pattern", action="append", required=True)
    parser.add_argument("--exclude", action="append", default=[])
    return parser.parse_args()


def iter_files(root: Path, excludes: list[str]):
    for directory, directories, filenames in os.walk(root, topdown=True, followlinks=False):
        directories[:] = [name for name in directories if name != ".git"]
        for filename in filenames:
            path = Path(directory) / filename
            relative = path.relative_to(root).as_posix()
            if any(
                fnmatch.fnmatch(relative, pattern)
                or fnmatch.fnmatch(path.name, pattern)
                for pattern in excludes
            ):
                continue
            yield path, relative


def main() -> int:
    args = parse_args()
    try:
        patterns = [re.compile(pattern) for pattern in args.pattern]
    except re.error as exc:
        print(f"invalid scan pattern: {exc}", file=sys.stderr)
        return 2

    for path, relative in iter_files(args.root, args.exclude):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            print(f"unable to read {relative}: {exc}", file=sys.stderr)
            return 2
        for line_number, line in enumerate(text.splitlines(), start=1):
            if any(pattern.search(line) for pattern in patterns):
                # Keep findings location-only. The caller can redact the report
                # category without placing matched values in CI logs.
                print(f"{relative}:{line_number}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
