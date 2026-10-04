from __future__ import annotations

import json
from pathlib import Path

from scripts.staging.acceptance_smoke import AcceptanceError, run_acceptance


_RUNTIME = (
    "infra/staging/docker-compose.yml",
    "infra/staging/.env.example",
    "scripts/staging/validate_runtime.py",
    "scripts/staging/run-smoke.sh",
)


def _runtime_fixture(root: Path, *, include_flow: bool) -> None:
    for relative in _RUNTIME:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("synthetic fixture\n", encoding="utf-8")
    resilience = root / "scripts/staging/resilience_smoke.py"
    resilience.parent.mkdir(parents=True, exist_ok=True)
    resilience.write_text("# synthetic fixture\n", encoding="utf-8")
    if include_flow:
        (root / "scripts/staging_e2e.py").write_text("# synthetic fixture\n", encoding="utf-8")


def test_missing_full_flow_is_explicitly_deferred_and_redacted(tmp_path: Path) -> None:
    _runtime_fixture(tmp_path, include_flow=False)
    calls: list[str] = []

    def runner(path: Path, functions: object) -> object:
        calls.append(path.name)
        return {"redacted_field": "synthetic-only", "count": 1}

    summary = run_acceptance(tmp_path, require_full_flow=False, runner=runner)
    assert summary["status"] == "passed_with_deferred"
    assert summary["deferred_stages"] == ["patient_flow"]
    assert summary["failed_stage"] is None
    assert calls == ["resilience_smoke.py"]
    assert "redacted_field" not in json.dumps(summary)


def test_full_flow_failure_identifies_the_stage(tmp_path: Path) -> None:
    _runtime_fixture(tmp_path, include_flow=True)

    def runner(path: Path, functions: object) -> object:
        if path.name == "staging_e2e.py":
            raise RuntimeError("synthetic harness failure")
        return {"ok": True}

    summary = run_acceptance(tmp_path, runner=runner)
    assert summary["status"] == "failed"
    assert summary["failed_stage"] == "patient_flow"
    patient_flow = next(stage for stage in summary["stages"] if stage["name"] == "patient_flow")
    assert patient_flow["details"]["error_code"] == "entrypoint_failed"
    assert patient_flow["details"]["exception_type"] == "RuntimeError"


def test_required_full_flow_missing_returns_blocked(tmp_path: Path) -> None:
    _runtime_fixture(tmp_path, include_flow=False)

    def runner(path: Path, functions: object) -> object:
        if not path.is_file():
            raise AcceptanceError("entrypoint_missing", {"entrypoint": path.name})
        return {"ok": True}

    summary = run_acceptance(tmp_path, require_full_flow=True, runner=runner)
    assert summary["status"] == "failed"
    assert summary["failed_stage"] == "patient_flow"
    patient_flow = next(stage for stage in summary["stages"] if stage["name"] == "patient_flow")
    assert patient_flow["details"]["error_code"] == "entrypoint_missing"
