#!/usr/bin/env python3
"""Compose provider-neutral staging harnesses into one acceptance entrypoint.

The entrypoint only orchestrates existing synthetic harnesses. It never creates
document payloads, persists raw bytes, or prints harness results; the summary
contains stage names, statuses, and result shapes only.
"""

from __future__ import annotations

import argparse
import json
import runpy
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RUNTIME_FILES = (
    Path("infra/staging/docker-compose.yml"),
    Path("infra/staging/.env.example"),
    Path("scripts/staging/validate_runtime.py"),
    Path("scripts/staging/run-smoke.sh"),
)
_FULL_FLOW = Path("scripts/staging_e2e.py")
_RESILIENCE = Path("scripts/staging/resilience_smoke.py")


class AcceptanceError(RuntimeError):
    """A deterministic, machine-readable acceptance failure."""

    def __init__(self, code: str, details: Mapping[str, object] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.details = dict(details or {})


@dataclass(frozen=True)
class StageResult:
    name: str
    status: str
    details: Mapping[str, object]


Runner = Callable[[Path, Sequence[str]], object]


def _runtime_contract(root: Path) -> Mapping[str, object]:
    missing = [str(path) for path in _RUNTIME_FILES if not (root / path).is_file()]
    if missing:
        raise AcceptanceError("runtime_contract_missing", {"missing_files": missing})
    return {"required_file_count": len(_RUNTIME_FILES), "compose_contract": "available"}


def _invoke_entrypoint(path: Path, functions: Sequence[str]) -> object:
    if not path.is_file():
        raise AcceptanceError("entrypoint_missing", {"entrypoint": path.name})
    namespace = runpy.run_path(str(path), run_name=f"_staging_acceptance_{path.stem}")
    for function_name in functions:
        function = namespace.get(function_name)
        if callable(function):
            return function()
    raise AcceptanceError(
        "entrypoint_callable_missing",
        {"entrypoint": path.name, "expected_functions": list(functions)},
    )


def _shape(value: object) -> Mapping[str, object]:
    """Keep result metadata safe without copying arbitrary harness output."""

    if isinstance(value, Mapping):
        return {"result_type": "mapping", "field_count": len(value)}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return {"result_type": "sequence", "result_length": len(value)}
    return {"result_type": type(value).__name__}


def _stage(
    name: str,
    callback: Callable[[], object],
) -> StageResult:
    try:
        result = callback()
    except AcceptanceError as exc:
        return StageResult(name, "failed", {"error_code": exc.code, **exc.details})
    except Exception as exc:  # pragma: no cover - exercised by integration CI
        return StageResult(
            name,
            "failed",
            {"error_code": "entrypoint_failed", "exception_type": type(exc).__name__},
        )
    return StageResult(name, "passed", _shape(result))


def _summary(stages: Sequence[StageResult]) -> dict[str, object]:
    failed = [stage.name for stage in stages if stage.status == "failed"]
    blocked = [stage.name for stage in stages if stage.status == "blocked"]
    deferred = [stage.name for stage in stages if stage.status == "deferred"]
    if failed:
        status = "failed"
        failed_stage = failed[0]
    elif blocked:
        status = "blocked"
        failed_stage = blocked[0]
    elif deferred:
        status = "passed_with_deferred"
        failed_stage = None
    else:
        status = "passed"
        failed_stage = None
    return {
        "schema": "staging-acceptance.v1",
        "status": status,
        "failed_stage": failed_stage,
        "deferred_stages": deferred,
        "synthetic_only": True,
        "raw_bytes_logged": False,
        "stages": [
            {"name": stage.name, "status": stage.status, "details": dict(stage.details)}
            for stage in stages
        ],
    }


def run_acceptance(
    repo_root: Path | None = None,
    *,
    require_full_flow: bool = True,
    runner: Runner = _invoke_entrypoint,
) -> dict[str, object]:
    """Run the runtime contract, retry/idempotency, and full patient flow.

    The full flow is supplied by the existing scripts/staging_e2e.py harness.
    A branch that intentionally does not yet contain that companion change can
    use require_full_flow=False; it receives a deferred stage rather than a
    false pass. The default command requires the complete flow.
    """

    root = (repo_root or _REPO_ROOT).resolve()
    stages: list[StageResult] = [
        _stage("runtime_composition", lambda: _runtime_contract(root)),
        _stage(
            "retry_and_idempotency",
            lambda: runner(root / _RESILIENCE, ("run_all",)),
        ),
    ]

    flow_path = root / _FULL_FLOW
    if not flow_path.is_file() and not require_full_flow:
        stages.append(
            StageResult(
                "patient_flow",
                "deferred",
                {
                    "reason_code": "full_flow_harness_not_present",
                    "entrypoint": flow_path.name,
                },
            )
        )
    else:
        stages.append(
            _stage(
                "patient_flow",
                lambda: runner(flow_path, ("run",)),
            )
        )
    return _summary(stages)


def _exit_code(summary: Mapping[str, object]) -> int:
    status = summary.get("status")
    if status in {"passed", "passed_with_deferred"}:
        return 0
    if status == "blocked":
        return 2
    return 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-missing-full-flow",
        action="store_true",
        help="defer the existing staging_e2e.py harness when it is not in this checkout",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="also write the redacted JSON summary to this path",
    )
    args = parser.parse_args(argv)

    summary = run_acceptance(require_full_flow=not args.allow_missing_full_flow)
    encoded = json.dumps(summary, ensure_ascii=False, sort_keys=True)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return _exit_code(summary)


if __name__ == "__main__":
    raise SystemExit(main())
