"""Loading and creating synthetic golden-set fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .schema import Claim, Conflict, GoldenCase, GoldenSet, claim_from_dict


def _conflict_from_dict(value: Mapping[str, Any]) -> Conflict:
    required = {"conflict_id", "claim_ids", "severity"}
    missing = sorted(required - set(value))
    if missing:
        raise ValueError(f"conflict is missing required fields: {', '.join(missing)}")
    return Conflict(
        conflict_id=value["conflict_id"],
        claim_ids=tuple(value["claim_ids"]),
        severity=value["severity"],
        reason=value.get("reason", ""),
    )


def golden_set_from_dict(value: Mapping[str, Any]) -> GoldenSet:
    required = {"dataset_id", "version", "data_classification", "cases"}
    missing = sorted(required - set(value))
    if missing:
        raise ValueError(f"golden set is missing required fields: {', '.join(missing)}")

    cases: list[GoldenCase] = []
    for raw_case in value["cases"]:
        document = raw_case.get("document", {})
        for field_name in ("source_ref", "source_type", "text"):
            if field_name not in document:
                raise ValueError(f"case document is missing required field: {field_name}")
        cases.append(
            GoldenCase(
                case_id=raw_case["case_id"],
                data_classification=raw_case.get("data_classification", value["data_classification"]),
                document_source_ref=document["source_ref"],
                document_source_type=document["source_type"],
                document_text=document["text"],
                expected_claims=tuple(claim_from_dict(item) for item in raw_case.get("expected_claims", [])),
                expected_conflicts=tuple(_conflict_from_dict(item) for item in raw_case.get("expected_conflicts", [])),
            )
        )
    return GoldenSet(
        dataset_id=value["dataset_id"],
        version=value["version"],
        data_classification=value["data_classification"],
        cases=tuple(cases),
    )


def load_golden_set(path: str | Path) -> GoldenSet:
    """Load a JSON golden set and validate every required field."""

    with Path(path).open(encoding="utf-8") as handle:
        return golden_set_from_dict(json.load(handle))


def _fact_line(claim: Claim) -> str:
    payload = {
        "claim_id": claim.claim_id,
        "text_en": claim.text_en,
        "text_zh": claim.text_zh,
        "source_ref": claim.source_ref,
        "source_type": claim.source_type,
        "confidence": claim.confidence,
        "review_status": claim.review_status.value,
        "normalized_key": claim.normalized_key,
        "normalized_value": claim.normalized_value,
    }
    return "FACT\t" + json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def synthetic_golden_set() -> GoldenSet:
    """Return a tiny, deterministic fixture containing only invented values."""

    medication_a = Claim(
        claim_id="synthetic-medication-001",
        text_en="Example medication A is listed as active.",
        text_zh="示例药物 A 标记为正在使用。",
        source_ref="synthetic:medication:page-1",
        source_type="synthetic_medication_list",
        confidence=1.0,
        review_status="accepted",
        normalized_key="medication:example-a:status",
        normalized_value="active",
    )
    dose_a = Claim(
        claim_id="synthetic-medication-002",
        text_en="Example medication A is taken once daily.",
        text_zh="示例药物 A 每日服用一次。",
        source_ref="synthetic:medication:page-1",
        source_type="synthetic_medication_list",
        confidence=1.0,
        review_status="accepted",
        normalized_key="medication:example-a:frequency",
        normalized_value="once_daily",
    )
    conflicting_old = Claim(
        claim_id="synthetic-conflict-001",
        text_en="Example medication B is taken once daily.",
        text_zh="示例药物 B 每日服用一次。",
        source_ref="synthetic:conflict:page-1",
        source_type="synthetic_visit_note",
        confidence=1.0,
        review_status="needs_review",
        normalized_key="medication:example-b:frequency",
        normalized_value="once_daily",
    )
    conflicting_new = Claim(
        claim_id="synthetic-conflict-002",
        text_en="Example medication B is taken twice daily.",
        text_zh="示例药物 B 每日服用两次。",
        source_ref="synthetic:conflict:page-2",
        source_type="synthetic_visit_note",
        confidence=1.0,
        review_status="needs_review",
        normalized_key="medication:example-b:frequency",
        normalized_value="twice_daily",
    )
    return GoldenSet(
        dataset_id="patient-app-ai-synthetic",
        version="1.0.0",
        data_classification="synthetic",
        cases=(
            GoldenCase(
                case_id="synthetic-medication",
                document_source_ref="synthetic:medication",
                document_source_type="synthetic_medication_list",
                document_text="\n".join((_fact_line(medication_a), _fact_line(dose_a))),
                expected_claims=(medication_a, dose_a),
            ),
            GoldenCase(
                case_id="synthetic-conflict",
                document_source_ref="synthetic:conflict",
                document_source_type="synthetic_visit_note",
                document_text="\n".join((_fact_line(conflicting_old), _fact_line(conflicting_new))),
                expected_claims=(conflicting_old, conflicting_new),
                expected_conflicts=(
                    Conflict(
                        conflict_id="synthetic-conflict-frequency",
                        claim_ids=(conflicting_old.claim_id, conflicting_new.claim_id),
                        severity="high",
                        reason="The same synthetic medication has two source frequencies.",
                    ),
                ),
            ),
        ),
    )
