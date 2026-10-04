"""Minimal offline CLI for the golden-set regression report."""

from __future__ import annotations

import argparse
from pathlib import Path

from .regression_report import generate_regression_report_from_json


def main(argv: list[str] | None = None) -> int:
    default_fixture = Path(__file__).parent / "fixtures" / "synthetic_golden_set.json"
    parser = argparse.ArgumentParser(description="Generate an offline AI golden-set regression report")
    parser.add_argument("--golden-set", type=Path, default=default_fixture, help="synthetic/de-identified golden-set JSON")
    args = parser.parse_args(argv)
    print(generate_regression_report_from_json(str(args.golden_set)).to_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
