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
per-case cost.

High and critical errors, unresolved conflicts, missing claims and provenance
failures set `delivery_blocked=true`. A report can therefore be used as a
delivery gate without treating a metric average as a safety decision.

Run the boundary checks from the repository root:

```sh
python3 -m unittest discover -s services/ai/tests -v
```
