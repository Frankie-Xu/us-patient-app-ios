# US Patient App · iOS

Public source-available repository for a bilingual patient app that organizes medical records into source-traceable visit preparation packs. The MVP loop is:

`upload → review → generate → share → continue`

The product is a patient-controlled organization and delivery tool. It does not diagnose, recommend treatment, interpret images, write back to an EHR, or replace clinical judgment.

## Repository layout

```text
apps/ios/          SwiftUI application and feature modules
services/api/      Auth, documents, facts, visits, tasks, sharing, audit
services/ai/       OCR, extraction, translation, conflict detection, evaluation
packages/contracts OpenAPI and shared data contracts
docs/              Architecture, technology route, decision records, evaluation
scripts/           Local validation and developer utilities
```

## Engineering baseline

- SwiftUI with feature-level MVVM/use cases and Swift Concurrency.
- Server-owned facts and versions; the client renders source, confidence and review state.
- OpenAPI-generated Swift networking once the API contract is frozen.
- Source references on every claim; high-severity unmarked errors block delivery.
- No PHI in logs, test fixtures, screenshots, analytics events or pull request text.
- Small branches, focused commits, required review, CI on every pull request.

## Start here

1. Read [`docs/technology-route.md`](docs/technology-route.md) and [`docs/architecture/README.md`](docs/architecture/README.md).
2. Read the product source and the iOS report that motivated this repository.
3. Resolve the open decisions in [`docs/wayfinder-map.md`](docs/wayfinder-map.md) before freezing external contracts.
4. Copy `.env.example` to a local environment file only when a service requires it; never commit credentials.

## Quality gates

Every feature must have empty, loading, failure, retry, success and permission-boundary states. API changes update the OpenAPI contract first. AI changes rerun the de-identified golden set and the high-severity error list. A shareable report must display version, source coverage and the limits of revocation.

## License and commercial use

This repository is public for review, research, and non-commercial collaboration. The software is licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE).

Commercial use is not permitted without a separate written license from the copyright holder. This includes using, selling, offering, hosting, deploying, integrating, or providing the software as part of a paid product or service. Forks, copies, and modifications must keep the same commercial-use restriction. Third-party dependencies remain under their own licenses.

This is source-available software, not an OSI-approved open-source license. The license does not grant rights to the product name, trademarks, branding, data, or patient content.

## Data use

Do not add real patient records. Use synthetic or appropriately de-identified fixtures only after the data-handling decision is recorded.
