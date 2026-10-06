-- PostgreSQL staging baseline for the patient app service boundary.
-- The migration stores metadata, immutable versions, object references and
-- processing state only. Raw document bytes remain in object storage.
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY,
    owner_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    media_type TEXT NOT NULL,
    size_bytes BIGINT NOT NULL CHECK (size_bytes BETWEEN 1 AND 10485760),
    sha256 CHAR(64) NOT NULL CHECK (sha256 ~ '^[0-9a-fA-F]{64}$'),
    source_type TEXT NOT NULL DEFAULT 'uploaded_document',
    status TEXT NOT NULL DEFAULT 'uploaded'
        CHECK (status IN ('uploaded', 'processing', 'ready', 'failed', 'deleted')),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS documents_owner_created_idx
    ON documents (owner_id, created_at DESC);

CREATE TABLE IF NOT EXISTS document_versions (
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    version INTEGER NOT NULL CHECK (version > 0),
    filename TEXT NOT NULL,
    media_type TEXT NOT NULL,
    size_bytes BIGINT NOT NULL CHECK (size_bytes BETWEEN 1 AND 10485760),
    sha256 CHAR(64) NOT NULL CHECK (sha256 ~ '^[0-9a-fA-F]{64}$'),
    object_key TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (document_id, version)
);

CREATE TABLE IF NOT EXISTS upload_sessions (
    id UUID PRIMARY KEY,
    owner_id TEXT NOT NULL,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    document_version INTEGER NOT NULL CHECK (document_version > 0),
    size_bytes BIGINT NOT NULL CHECK (size_bytes BETWEEN 1 AND 10485760),
    sha256 CHAR(64) NOT NULL CHECK (sha256 ~ '^[0-9a-fA-F]{64}$'),
    media_type TEXT NOT NULL,
    object_key TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'verified')),
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    verified_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS upload_sessions_document_idx
    ON upload_sessions (document_id, created_at DESC);

CREATE TABLE IF NOT EXISTS facts (
    id UUID PRIMARY KEY,
    owner_id TEXT NOT NULL,
    document_id UUID REFERENCES documents(id) ON DELETE SET NULL,
    document_version INTEGER,
    label TEXT NOT NULL,
    value TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    source_start INTEGER,
    source_end INTEGER,
    source_type TEXT NOT NULL,
    confidence DOUBLE PRECISION NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    review_status TEXT NOT NULL DEFAULT 'unreviewed'
        CHECK (review_status IN ('unreviewed', 'in_review', 'confirmed', 'rejected', 'superseded')),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS facts_owner_document_idx
    ON facts (owner_id, document_id, created_at DESC);

CREATE TABLE IF NOT EXISTS topics (
    id UUID PRIMARY KEY,
    owner_id TEXT NOT NULL,
    name TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS visits (
    id UUID PRIMARY KEY,
    owner_id TEXT NOT NULL,
    title TEXT NOT NULL,
    starts_at TIMESTAMPTZ,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS visit_topics (
    visit_id UUID NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
    topic_id UUID NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    PRIMARY KEY (visit_id, topic_id)
);
CREATE TABLE IF NOT EXISTS visit_documents (
    visit_id UUID NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    PRIMARY KEY (visit_id, document_id)
);
CREATE TABLE IF NOT EXISTS tasks (
    id UUID PRIMARY KEY,
    owner_id TEXT NOT NULL,
    visit_id UUID REFERENCES visits(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'done', 'cancelled')),
    due_at TIMESTAMPTZ,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS tasks_owner_visit_idx
    ON tasks (owner_id, visit_id, created_at DESC);

CREATE TABLE IF NOT EXISTS processing_jobs (
    id UUID PRIMARY KEY,
    owner_id TEXT NOT NULL,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    job_type TEXT NOT NULL CHECK (job_type IN ('ocr', 'extract_facts', 'translate', 'render_share')),
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    idempotency_key TEXT NOT NULL,
    request_hash CHAR(64) NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    attempt INTEGER NOT NULL DEFAULT 0 CHECK (attempt >= 0),
    max_attempts INTEGER NOT NULL DEFAULT 3 CHECK (max_attempts > 0),
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    locked_by TEXT,
    locked_at TIMESTAMPTZ,
    error_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (owner_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS processing_jobs_claim_idx
    ON processing_jobs (status, next_attempt_at, created_at);

CREATE TABLE IF NOT EXISTS processing_job_attempts (
    id BIGSERIAL PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES processing_jobs(id) ON DELETE CASCADE,
    attempt INTEGER NOT NULL CHECK (attempt > 0),
    worker_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    error_code TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    UNIQUE (job_id, attempt)
);

CREATE TABLE IF NOT EXISTS share_versions (
    id UUID PRIMARY KEY,
    owner_id TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id UUID NOT NULL,
    resource_version INTEGER NOT NULL CHECK (resource_version > 0),
    token_digest CHAR(64) NOT NULL CHECK (token_digest ~ '^[0-9a-f]{64}$'),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'expired', 'revoked')),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS share_versions_lookup_idx
    ON share_versions (resource_type, resource_id, status, expires_at);

-- Deterministic content deduplication and intake metadata. These indexes do
-- not retain bytes and remain compatible with the provider-neutral API.
CREATE UNIQUE INDEX IF NOT EXISTS documents_owner_content_active_idx
    ON documents (owner_id, sha256, media_type, size_bytes)
    WHERE status <> 'deleted';

CREATE TABLE IF NOT EXISTS document_intake_metadata (
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    document_version INTEGER NOT NULL CHECK (document_version > 0),
    detected_media_type TEXT NOT NULL,
    container_type TEXT NOT NULL,
    page_count INTEGER CHECK (page_count IS NULL OR page_count > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (document_id, document_version)
);
CREATE INDEX IF NOT EXISTS document_intake_metadata_type_idx
    ON document_intake_metadata (detected_media_type, container_type);

CREATE TABLE IF NOT EXISTS audit_events (
    id UUID PRIMARY KEY,
    actor_id TEXT NOT NULL,
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS audit_events_actor_time_idx
    ON audit_events (actor_id, occurred_at DESC);
