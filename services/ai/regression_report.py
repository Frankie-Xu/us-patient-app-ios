"""Offline, JSON-serialisable golden-set regression report."""

from __future__ import annotations

import json
from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping

from .api_projection import API_VERSION
from .golden_set import load_golden_set
from .pipeline import DeterministicStubPipeline, EvaluationPipeline
from .reporting import METRIC_FIELDS, evaluate_golden_set
from .schema import GoldenSet


REPORT_FIELDS = (
    "api_version",
    "dataset_id",
    "dataset_version",
    "sample_count",
    "pipeline",
    "metrics",
    "error_categories",
    "delivery_blocked",
)


@dataclass(frozen=True)
class GoldenSetRegressionReport:
    """Stable summary consumed by a release or API review gate."""

    api_version: str
    dataset_id: str
    dataset_version: str
    sample_count: int
    pipeline: str
    metrics: dict[str, float]
    error_categories: dict[str, int]
    delivery_blocked: bool

    def __post_init__(self) -> None:
        if self.api_version != API_VERSION:
            raise ValueError(f"report requires API version {API_VERSION}")
        if not isinstance(self.dataset_id, str) or not self.dataset_id.strip():
            raise ValueError("dataset_id must be a non-empty string")
        if not isinstance(self.dataset_version, str) or not self.dataset_version.strip():
            raise ValueError("dataset_version must be a non-empty string")
        if type(self.sample_count) is not int or self.sample_count < 1:
            raise ValueError("sample_count must be a positive integer")
        if not isinstance(self.pipeline, str) or not self.pipeline.strip():
            raise ValueError("pipeline must be a non-empty string")
        if not isinstance(self.delivery_blocked, bool):
            raise ValueError("delivery_blocked must be a boolean")
        normalized_metrics: dict[str, float] = {}
        for name, value in self.metrics.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError("metric names must be non-empty strings")
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(float(value)):
                raise ValueError(f"metric {name} must be finite")
            normalized_metrics[name] = float(value)
        normalized_errors: dict[str, int] = {}
        for code, count in self.error_categories.items():
            if not isinstance(code, str) or not code.strip():
                raise ValueError("error category names must be non-empty strings")
            if type(count) is not int or count < 1:
                raise ValueError("error category counts must be positive integers")
            normalized_errors[code] = count
        if not set(METRIC_FIELDS) <= set(normalized_metrics):
            missing = sorted(set(METRIC_FIELDS) - set(normalized_metrics))
            raise ValueError(f"report is missing required metrics: {', '.join(missing)}")
        object.__setattr__(self, "metrics", dict(sorted(normalized_metrics.items())))
        object.__setattr__(self, "error_categories", dict(sorted(normalized_errors.items())))

    def to_dict(self) -> dict[str, Any]:
        return {
            "api_version": self.api_version,
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "sample_count": self.sample_count,
            "pipeline": self.pipeline,
            "metrics": dict(self.metrics),
            "error_categories": dict(self.error_categories),
            "delivery_blocked": self.delivery_blocked,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "GoldenSetRegressionReport":
        missing = sorted(set(REPORT_FIELDS) - set(value))
        if missing:
            raise ValueError(f"report is missing fields: {', '.join(missing)}")
        return cls(
            api_version=value["api_version"],
            dataset_id=value["dataset_id"],
            dataset_version=value["dataset_version"],
            sample_count=value["sample_count"],
            pipeline=value["pipeline"],
            metrics=dict(value["metrics"]),
            error_categories=dict(value["error_categories"]),
            delivery_blocked=value["delivery_blocked"],
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, value: str) -> "GoldenSetRegressionReport":
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"report is not valid JSON: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise ValueError("report JSON must contain an object")
        return cls.from_dict(payload)


def generate_regression_report(
    golden_set: GoldenSet,
    pipeline: EvaluationPipeline | None = None,
    *,
    per_case_cost: float | None = None,
) -> GoldenSetRegressionReport:
    """Run the deterministic evaluation and return its stable JSON summary."""

    report = evaluate_golden_set(golden_set, pipeline or DeterministicStubPipeline(), per_case_cost)
    error_categories: dict[str, int] = {}
    for case in report.cases:
        for error in case.errors:
            error_categories[error.code] = error_categories.get(error.code, 0) + 1
    return GoldenSetRegressionReport(
        api_version=API_VERSION,
        dataset_id=golden_set.dataset_id,
        dataset_version=golden_set.version,
        sample_count=len(golden_set.cases),
        pipeline=report.pipeline,
        metrics=report.metrics,
        error_categories=error_categories,
        delivery_blocked=report.delivery_blocked,
    )


def generate_regression_report_from_json(path: str) -> GoldenSetRegressionReport:
    """Load a local golden-set JSON fixture and produce its report."""

    return generate_regression_report(load_golden_set(path))
