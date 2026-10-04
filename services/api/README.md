# API service skeleton

The core in `models.py`, `store.py`, and `service.py` is typed with Python stdlib dataclasses and an explicit in-memory adapter. It provides the use-case boundary for documents, source-traceable facts, topics, visits, tasks, upload jobs, shares, idempotency, immutable version checks, and audit events.

`app.py` is an optional FastAPI adapter. Install the dependencies declared in `pyproject.toml` to run HTTP routes; authentication remains a gateway concern and is represented in the core by `AuthContext` and scopes. Replace `InMemoryStore` with a transactional database/object-storage adapter before handling production PHI.

Run the dependency-free tests from the repository root:

```sh
python3 -m unittest discover -s services/api/tests -p 'test_*.py'
```

## HTTP adapter

`app.py` exposes `create_app()` when the optional FastAPI dependencies are installed. The framework-neutral `ApiHttpAdapter` is the local integration seam used by tests. Its temporary bearer header format is `Bearer <subject>|<comma-separated scopes>|<comma-separated roles>`; this only adapts test headers to `AuthContext` and does not validate production credentials.

`ApiService` accepts `ObjectStore` and `JobQueue` protocols through dependency injection. `InMemoryObjectStore` and `InMemoryJobQueue` are local doubles only; no network, credentials, or real patient payloads are used. `/healthz` reports process liveness, while `/readyz` reports metadata, object-store, and queue availability and returns `503` when any dependency is unavailable.


HTTP errors use the stable envelope `{ "code": "...", "detail": "..." }`. Current codes are `AUTHENTICATION_REQUIRED`, `FORBIDDEN`, `NOT_FOUND`, `SHARE_NOT_FOUND`, `IDEMPOTENCY_CONFLICT`, `VERSION_CONFLICT`, `VALIDATION_ERROR`, `SERVICE_ERROR`, `SHARE_EXPIRED`, `SHARE_REVOKED`, `DEPENDENCY_UNAVAILABLE`, and `INTERNAL_ERROR`. Details are kept operational and never echo request bodies, filenames, claims, or tokens.

The HTTP adapter also exposes the frozen visit-preparation writes: `POST /v1/topics`, `POST /v1/visits`, and `POST /v1/tasks`. Visit and task timestamps require timezone-aware ISO-8601 values; `topic_ids` is an array and `visit_id` is nullable.
