# API service skeleton

The core in `models.py`, `store.py`, and `service.py` is typed with Python stdlib dataclasses and an explicit in-memory adapter. It provides the use-case boundary for documents, source-traceable facts, topics, visits, tasks, upload jobs, shares, idempotency, immutable version checks, and audit events.

`app.py` is an optional FastAPI adapter. Install the dependencies declared in `pyproject.toml` to run HTTP routes; authentication remains a gateway concern and is represented in the core by `AuthContext` and scopes. Replace `InMemoryStore` with a transactional database/object-storage adapter before handling production PHI.

Run the dependency-free tests from the repository root:

```sh
python3 -m unittest discover -s services/api/tests -p 'test_*.py'
```
