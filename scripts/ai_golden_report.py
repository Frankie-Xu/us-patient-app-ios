"""Run the deterministic synthetic golden set and print aggregate metrics only."""
from __future__ import annotations

import math
import json
from dataclasses import replace
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


def _doctor_view_gate(golden_set: Any) -> dict[str, Any]:
    from services.ai.api_projection import project_evaluation
    from services.ai.doctor_view import evaluate_doctor_view
    from services.ai.output_evaluator import evaluate_extraction_output
    from services.ai.pipeline import DeterministicStubPipeline

    pipeline = DeterministicStubPipeline()
    counts = {
        "doctor_view_claim_count": 0,
        "doctor_view_review_item_count": 0,
        "doctor_view_review_required_gap_count": 0,
        "doctor_view_confirmation_leak_count": 0,
        "doctor_view_source_gap_count": 0,
        "doctor_view_included_count": 0,
        "doctor_view_excluded_count": 0,
        "doctor_view_negative_included_count": 0,
        "doctor_view_conflict_included_count": 0,
        "doctor_view_expected_inclusion_gap_count": 0,
        "doctor_view_error_count": 0,
    }
    for case in golden_set.cases:
        output = pipeline.run(case)
        evaluation = evaluate_extraction_output(case, output.extraction.claims, ocr_blocks=output.ocr.blocks)
        projection = project_evaluation(evaluation, output.extraction.claims, conflicts=output.conflicts.conflicts)
        counts["doctor_view_claim_count"] += len(projection.fact_creates)
        counts["doctor_view_review_item_count"] += len(projection.fact_reviews)
        projected_items = (*projection.fact_creates, *projection.fact_reviews)
        counts["doctor_view_review_required_gap_count"] += sum(not item.review_required for item in projected_items)
        counts["doctor_view_confirmation_leak_count"] += sum(
            getattr(item.review_status, "value", item.review_status) == "confirmed" for item in projected_items
        )
        counts["doctor_view_source_gap_count"] += sum(not item.source_ref for item in projection.fact_creates)
        counts["doctor_view_source_gap_count"] += sum(
            not item.source_ref and getattr(item.review_status, "value", item.review_status) != "rejected"
            for item in projection.fact_reviews
        )
        confirmed_claims = tuple(replace(claim, review_status="confirmed") for claim in output.extraction.claims)
        confirmed_gate = evaluate_doctor_view(confirmed_claims, conflicts=output.conflicts.conflicts)
        negative_gate = evaluate_doctor_view(output.extraction.claims, conflicts=output.conflicts.conflicts)
        counts["doctor_view_included_count"] += len(confirmed_gate.included_claim_ids)
        counts["doctor_view_excluded_count"] += len(confirmed_gate.excluded_claim_ids)
        counts["doctor_view_negative_included_count"] += len(negative_gate.included_claim_ids)
        counts["doctor_view_conflict_included_count"] += (
            len(confirmed_gate.included_claim_ids) if output.conflicts.conflicts else 0
        )
        expected_included = 0 if output.conflicts.conflicts else len(output.extraction.claims)
        counts["doctor_view_expected_inclusion_gap_count"] += abs(
            expected_included - len(confirmed_gate.included_claim_ids)
        )
        counts["doctor_view_error_count"] += sum(confirmed_gate.error_categories.values())
        counts["doctor_view_error_count"] += sum(negative_gate.error_categories.values())
    counts["doctor_view_gate_passed"] = all(
        counts[name] == 0
        for name in (
            "doctor_view_review_required_gap_count",
            "doctor_view_confirmation_leak_count",
            "doctor_view_source_gap_count",
            "doctor_view_negative_included_count",
            "doctor_view_conflict_included_count",
            "doctor_view_expected_inclusion_gap_count",
        )
    )
    return counts


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
        doctor_view = _doctor_view_gate(golden_set)
        metrics = report.metrics
        required = ("precision", "recall", "citation_coverage", "review_required_recall")
        if any(metric not in metrics or not math.isfinite(float(metrics[metric])) for metric in required):
            raise ValueError("required aggregate metrics are missing")
        metrics_failed = any(float(metrics[metric]) < 1.0 for metric in required)
        if metrics_failed or not doctor_view["doctor_view_gate_passed"]:
            _write_result(
                artifact_path,
                "failed",
                dataset_version=report.dataset_version,
                case_count=len(report.cases),
                **{metric: float(metrics[metric]) for metric in required},
                blocking_error_count=len(report.blocking_errors),
                delivery_blocked=bool(report.delivery_blocked),
                **doctor_view,
            )
            reason = "aggregate safety metrics are below 1.0" if metrics_failed else "doctor-view gate regression detected"
            print(f"AI golden-set regression failed: {reason}.", file=sys.stderr)
            return 1
        _write_result(
            artifact_path,
            "passed",
            dataset_version=report.dataset_version,
            case_count=len(report.cases),
            **{metric: float(metrics[metric]) for metric in required},
            blocking_error_count=len(report.blocking_errors),
            delivery_blocked=bool(report.delivery_blocked),
            **doctor_view,
        )
        print(
            "AI golden-set regression passed "
            f"(dataset_version={report.dataset_version}, cases={len(report.cases)}, "
            f"precision={metrics['precision']:.3f}, recall={metrics['recall']:.3f}, "
            f"citation_coverage={metrics['citation_coverage']:.3f}, "
            f"review_required_recall={metrics['review_required_recall']:.3f}, "
            f"blocking_errors={len(report.blocking_errors)}, delivery_blocked={str(report.delivery_blocked).lower()}, "
            f"doctor_view_claims={doctor_view['doctor_view_claim_count']}, "
            f"doctor_view_reviews={doctor_view['doctor_view_review_item_count']}, "
            f"doctor_view_review_gaps={doctor_view['doctor_view_review_required_gap_count']}, "
            f"doctor_view_confirmation_leaks={doctor_view['doctor_view_confirmation_leak_count']}, "
            f"doctor_view_source_gaps={doctor_view['doctor_view_source_gap_count']}, "
            f"doctor_view_expected_gaps={doctor_view['doctor_view_expected_inclusion_gap_count']})."
        )
        return 0
    except Exception as exc:
        _write_result(artifact_path, "failed", error_type=type(exc).__name__)
        print(f"AI golden-set regression failed ({type(exc).__name__}); inspect the synthetic fixture locally.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]).resolve(), sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else ""))
