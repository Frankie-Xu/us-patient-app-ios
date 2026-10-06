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

`evaluate_doctor_view` is the final deterministic eligibility gate. It includes
only facts with `review_status=confirmed`, a complete `source_ref` and
`source_span`, and no unresolved conflict. It returns auditable included and
excluded claim IDs, stable `doctor_view.*` error categories and
`delivery_blocked`; the gate never changes a claim into `confirmed`.

`project_doctor_brief` is the bounded one-page projection on top of that gate.
It emits only verbatim, confirmed content with source spans, and preserves
patient goals and tasks when they are confirmed user-input claims. The caller
must provide an authenticated owner/visit scope and an authorization mapping
for every claim; missing mappings, scope mismatches, unresolved conflicts,
unconfirmed facts and missing provenance reject the whole brief. The fixed
budget is 12 facts, 4 goals, 6 tasks and 4,000 bilingual text characters;
overflow rejects rather than truncates. The projection never invents a
diagnosis, treatment, recommendation or priority. Its response is PHI and
must stay in the authorized response channel, out of logs and regression
artifacts. See [`doctor_brief.schema.json`](doctor_brief.schema.json).

High and critical errors, unresolved conflicts, missing claims and provenance
failures set `delivery_blocked=true`. A report can therefore be used as a
delivery gate without treating a metric average as a safety decision.

Run the boundary checks from the repository root:

```sh
python3 -m unittest discover -s services/ai/tests -v
```


### Provider-neutral runtime seam

provider_pipeline.py composes the existing OCR, extraction, conflict and citation interfaces without binding the repository to an OCR/model SDK. It normalizes OCR evidence while preserving source references, validates every claim source span, and generates a bounded bilingual doctor summary plus claim-grounded questions. ModelTelemetry records provider/model version, unit counts, cost and latency only; document text is never retained. The default deterministic adapter uses the synthetic golden set and remains compatible with the existing regression CLI.

### Deterministic staging worker

staging_worker.py accepts a normalized OCR document envelope marked
`synthetic` or `deidentified`. It creates a label-free
pipeline envelope, so expected golden labels cannot enter the runtime path.
`StagingAIWorker` caches completed work by an explicit idempotency key
(or a content fingerprint), returns the existing extraction and doctor-summary
artifacts, and rejects key reuse for a different document. The adapter is
provider-neutral; the built-in provider is deterministic and network-free.

`StagingQualityMetrics` reports low-confidence, missing-source,
conflict, manual-review and confirmation-block rates. Missing source includes
an absent or unresolved source span; a low-confidence claim or unresolved
conflict blocks automatic confirmation. Metrics are derived from counters and
aggregate by claim and case denominators. Telemetry contains only counts and
gate outcomes; OCR and claim text are not serialized.
