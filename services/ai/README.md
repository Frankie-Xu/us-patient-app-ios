
### Provider-neutral runtime seam

provider_pipeline.py composes the existing OCR, extraction, conflict and
citation interfaces without binding the repository to an OCR/model SDK. It
normalizes OCR evidence while preserving source references, validates every
claim source span, and generates a bounded bilingual doctor summary plus
claim-grounded questions. ModelTelemetry records provider/model version,
unit counts, cost and latency only; document text is never retained. The
default deterministic adapter uses the synthetic golden set and remains
compatible with the existing regression CLI.
