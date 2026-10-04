# AI evaluation boundary

This directory defines the offline contract for OCR/layout, bilingual fact
extraction, conflict detection, citation coverage and regression reporting.
It has no network client and never calls an external model provider.

The [golden-set schema](golden_set.schema.json) accepts only `synthetic` or
`deidentified` data. Every claim requires `claim_id`, `source_ref`,
`source_type`, `confidence` (0 to 1), and `review_status`. `text_en` and
`text_zh` make the bilingual extraction contract explicit. A claim produced by
the pipeline is always returned as `needs_review`; an accepted state must come
from an explicit review event outside this boundary.

`DeterministicStubPipeline` reads transparent `FACT<TAB>{json}` lines from a
synthetic document. It is a repeatable contract test double, not a clinical
parser. `evaluate_golden_set` returns per-case and aggregate fields for
precision, recall, citation coverage, rewrite rate, rejection rate and
per-case cost. `evaluate_extraction_output` additionally scores field values,
source spans, confidence error and review-required precision/recall. Its
`review_decisions` payload contains `claim_id`, `review_required`,
`review_status` and stable error categories for the API review queue.

`project_evaluation` maps this result to API v0.2.0 `FactCreate` and
`FactReview` payloads. Both payloads carry `claim_id`, source metadata,
confidence, error categories and `review_required=true`. Missing spans,
confidence below the projection threshold and detected conflicts add review
categories and remain `needs_review`; rejected inputs remain `rejected`.
The projection deserializer rejects `confirmed`, leaving confirmation to an
explicit API review event.

`route_compatibility.py` validates the HTTP JSON envelope and the checked-in
[`api_v0_2_projection.json`](fixtures/api_v0_2_projection.json) fixture. It
checks the frozen field set and version, requires every created fact to have a
matching review item, and rejects low-confidence, missing-span or conflict
payloads that omit their review category or attempt confirmation.

`fixed_mock_predictions` supplies deterministic variants for value mismatch,
source-span mismatch, low confidence, missing review, missing claims and
unexpected claims. These fixtures are synthetic test inputs only.

`generate_regression_report` produces the offline pilot exit artifact. Its
JSON is frozen by [`regression_report.schema.json`](regression_report.schema.json)
and contains `report_schema`, `schema_version`, `api_version`, dataset
identity, `sample_count`, quality metrics, stable `error_categories` counts
and `delivery_blocked`. Deserialization rejects unknown fields and schema or
API version drift. The same entry point is available from the CLI:

```sh
python3 -m services.ai.regression_cli \
  --golden-set services/ai/fixtures/synthetic_golden_set.json
```

The default synthetic fixture includes an unresolved high-severity conflict,
so its report is intentionally blocked. A clean case-only set demonstrates an
unblocked report in the regression tests.

High and critical errors, unresolved conflicts, missing claims and provenance
failures set `delivery_blocked=true`. A report can therefore be used as a
delivery gate without treating a metric average as a safety decision.

Run the boundary checks from the repository root:

```sh
python3 -m unittest discover -s services/ai/tests -v
```
