"""Run the deterministic synthetic golden set and print aggregate metrics only."""
from __future__ import annotations

import math
import json
from pathlib import Path
import sys
from typing import Any


def _write_result(path: str, status: str, **fields: Any) -> None:
    if not path:
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": 1, "check": "ai_golden_regression", "status": status, **fields}
    output.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def main(root: Path, component_dir: str, artifact_path: str = "") -> int:
    component_path = root / component_dir
    if not component_path.is_dir() or not (component_path / "golden_set.py").is_file():
        _write_result(artifact_path, "skipped", reason="evaluation_component_absent")
        print(f"Skipping AI golden-set regression: {component_dir} evaluation component is not present yet.")
        return 0

    sys.path.insert(0, str(root))
    try:
        from services.ai.golden_set import load_golden_set, synthetic_golden_set
        from services.ai.pipeline import DeterministicStubPipeline
        from services.ai.reporting import evaluate_golden_set

        fixture = root / component_dir / "fixtures" / "synthetic_golden_set.json"
        golden_set = load_golden_set(fixture) if fixture.is_file() else synthetic_golden_set()
        report = evaluate_golden_set(golden_set, DeterministicStubPipeline())
        metrics = report.metrics
        required = ("precision", "recall", "citation_coverage", "review_required_recall")
        if any(metric not in metrics or not math.isfinite(float(metrics[metric])) for metric in required):
            raise ValueError("required aggregate metrics are missing")
        if any(float(metrics[metric]) < 1.0 for metric in required):
            _write_result(
                artifact_path,
                "failed",
                dataset_version=report.dataset_version,
                case_count=len(report.cases),
                **{metric: float(metrics[metric]) for metric in required},
                blocking_error_count=len(report.blocking_errors),
                delivery_blocked=bool(report.delivery_blocked),
            )
            print("AI golden-set regression failed: aggregate safety metrics are below 1.0.", file=sys.stderr)
            return 1
        _write_result(
            artifact_path,
            "passed",
            dataset_version=report.dataset_version,
            case_count=len(report.cases),
            **{metric: float(metrics[metric]) for metric in required},
            blocking_error_count=len(report.blocking_errors),
            delivery_blocked=bool(report.delivery_blocked),
        )
        print(
            "AI golden-set regression passed "
            f"(dataset_version={report.dataset_version}, cases={len(report.cases)}, "
            f"precision={metrics['precision']:.3f}, recall={metrics['recall']:.3f}, "
            f"citation_coverage={metrics['citation_coverage']:.3f}, "
            f"review_required_recall={metrics['review_required_recall']:.3f}, "
            f"blocking_errors={len(report.blocking_errors)}, delivery_blocked={str(report.delivery_blocked).lower()})."
        )
        return 0
    except Exception as exc:
        _write_result(artifact_path, "failed", error_type=type(exc).__name__)
        print(f"AI golden-set regression failed ({type(exc).__name__}); inspect the synthetic fixture locally.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]).resolve(), sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else ""))
