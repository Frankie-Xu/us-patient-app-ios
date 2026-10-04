"""Run the deterministic synthetic golden set and print aggregate metrics only."""
from __future__ import annotations

import math
from pathlib import Path
import sys


def main(root: Path, component_dir: str) -> int:
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
            print("AI golden-set regression failed: aggregate safety metrics are below 1.0.", file=sys.stderr)
            return 1
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
        print(f"AI golden-set regression failed ({type(exc).__name__}); inspect the synthetic fixture locally.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]).resolve(), sys.argv[2]))
