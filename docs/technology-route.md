# Technology route and GitHub shortlist

This is a decision-ready shortlist, not an instruction to adopt every dependency. Candidate repositories were checked on 2026-10-04; licenses, release cadence, security posture, and PHI handling still require project-specific review before adoption.

## Recommended route

### iOS client

- **SwiftUI + Swift Concurrency** for the app shell, task-oriented navigation, upload state and review flows.
- **Apple Vision / PDFKit / PhotosUI** for device-side previews and lightweight preprocessing. Keep OCR and clinical-document extraction server-side until quality and privacy are measured.
- **Swift OpenAPI Generator + Runtime + URLSession transport** for a typed client generated from the contract. This keeps API drift visible in review.
- **Swift Testing** for domain/use-case tests and UI automation for the critical import → review → share path.
- **OpenTelemetry Swift** only after a redaction policy exists; do not export document text, claims, filenames or identifiers.

### Services

- **FastAPI + Pydantic** for the initial typed HTTP boundary and validation. Generate the OpenAPI contract from the service and consume it from iOS.
- **PostgreSQL** for relational state and immutable version metadata; object storage for encrypted originals and rendered outputs.
- **A durable job runner** for OCR/extraction/translation/summary jobs. Start with a provider-managed queue or a small worker service; choose Temporal/Celery only after the workload and operating model are clear.
- **PaddleOCR** is a candidate for multilingual document OCR/layout experiments. Treat it as an evaluation component, not as a clinical-quality guarantee.
- **OpenTelemetry** for redacted traces and operational metrics; keep audit events separate from observability telemetry.

## GitHub projects worth evaluating

| Area | Project | Why it fits | Adoption note |
|---|---|---|---|
| Typed API client | [apple/swift-openapi-generator](https://github.com/apple/swift-openapi-generator) | Generates Swift client/server code from OpenAPI | Apache-2.0; freeze the contract before generation |
| API runtime | [apple/swift-openapi-runtime](https://github.com/apple/swift-openapi-runtime) | Runtime for generated Swift clients | Apache-2.0; pair with the generator version |
| URLSession transport | [apple/swift-openapi-urlsession](https://github.com/apple/swift-openapi-urlsession) | Native URLSession transport | Apache-2.0; keep auth/retry policy in our repository |
| State architecture | [pointfreeco/swift-composable-architecture](https://github.com/pointfreeco/swift-composable-architecture) | Strong state/effect modeling for complex flows | Evaluate against a lighter MVVM/use-case baseline; avoid adding it before the team needs its conventions |
| Python API | [fastapi/fastapi](https://github.com/fastapi/fastapi) | OpenAPI-first async HTTP service | MIT; pin versions and run dependency/security checks |
| Validation | [pydantic/pydantic](https://github.com/pydantic/pydantic) | Typed request/response and domain validation | MIT; use explicit schemas for source and review state |
| OCR experiment | [PaddlePaddle/PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) | Multilingual OCR and document structure tooling | Apache-2.0; benchmark on de-identified golden data and track model versions |
| Swift telemetry | [open-telemetry/opentelemetry-swift](https://github.com/open-telemetry/opentelemetry-swift) | Standard tracing/metrics API for Swift | Apache-2.0; redact sensitive attributes before export |
| Python telemetry | [open-telemetry/opentelemetry-python](https://github.com/open-telemetry/opentelemetry-python) | Common service telemetry API | Apache-2.0; audit trails must remain a separate controlled store |
| Test doubles | [pointfreeco/swift-dependencies](https://github.com/pointfreeco/swift-dependencies) | Injectable clocks, clients and test dependencies | Evaluate if the project adopts TCA; otherwise use small local protocols |

## Projects to defer

- FHIR/EHR connectors until the service entity, data-processing agreements, supported institutions and source coverage are verified.
- Analytics/crash SDKs until PHI redaction, retention and vendor terms are approved.
- Large agent frameworks until the extraction and review contract is stable; deterministic pipelines are easier to evaluate and audit.
- Offline full-record storage until threat modeling proves that device storage is necessary.

## Selection gates

1. License and transitive dependency review.
2. Reproducible version pinning and software bill of materials.
3. De-identified golden-set evaluation for OCR and extraction.
4. No sensitive content in logs, traces, crash payloads or issue text.
5. Exit plan: every vendor or framework must be replaceable behind a protocol or service boundary.

