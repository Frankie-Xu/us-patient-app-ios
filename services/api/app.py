"""Optional FastAPI adapter for the dependency-light application service.

Install the declared service dependencies to expose HTTP routes. The domain
service remains importable and testable without FastAPI or a database.
"""
from __future__ import annotations

from .service import ApiService

try:  # pragma: no cover - exercised when optional HTTP dependencies are installed
    from fastapi import FastAPI, Header, HTTPException
    from pydantic import BaseModel, Field
except ImportError:  # pragma: no cover - default local environment
    FastAPI = None  # type: ignore[assignment]


def create_app(service: ApiService | None = None):
    if FastAPI is None:
        raise RuntimeError("FastAPI/Pydantic are optional; install services/api dependencies to run HTTP routes")
    api = FastAPI(title="US Patient App API", version="0.1.0", docs_url="/docs")
    app_service = service or ApiService()

    class DocumentCreate(BaseModel):
        filename: str = Field(min_length=1)
        media_type: str = Field(min_length=1)
        size_bytes: int = Field(ge=0)
        sha256: str = Field(min_length=64, max_length=64)

    @api.get("/healthz", tags=["system"])
    def healthz():
        return {"status": "ok"}

    @api.post("/v1/documents", status_code=201, tags=["documents"])
    def create_document(body: DocumentCreate, idempotency_key: str = Header(..., alias="Idempotency-Key")):
        from .models import AuthContext, Scope
        auth = AuthContext("http-principal", scopes=frozenset({Scope.DOCUMENTS_WRITE}))
        try:
            return app_service.create_document(auth, **body.model_dump(), idempotency_key=idempotency_key)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return api


app = None
if FastAPI is not None:  # keep import side effects small for tests
    app = create_app()
