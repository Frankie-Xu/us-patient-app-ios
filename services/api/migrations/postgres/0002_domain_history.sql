-- Domain persistence and append-only history for staging.
-- Depends on 0001_initial.sql. This migration stores opaque references and
-- metadata only; raw document bytes and direct identifiers stay out of SQL.
BEGIN;

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY,
    subject_ref TEXT NOT NULL
        CHECK (length(trim(subject_ref)) BETWEEN 1 AND 256
            AND subject_ref !~ '[[:space:]]'),
    locale TEXT NOT NULL DEFAULT 'en-US'
        CHECK (locale IN ('en-US', 'zh-Hans')),
    timezone TEXT NOT NULL DEFAULT 'UTC',
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'disabled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS users_subject_ref_uidx
    ON users (subject_ref);

CREATE TABLE IF NOT EXISTS patients (
    id UUID PRIMARY KEY,
    account_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    patient_ref TEXT NOT NULL
        CHECK (length(trim(patient_ref)) BETWEEN 1 AND 256
            AND patient_ref !~ '[[:space:]]'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (account_id, patient_ref)
);
CREATE INDEX IF NOT EXISTS patients_account_created_idx
    ON patients (account_id, created_at DESC);

CREATE TABLE IF NOT EXISTS cases (
    id UUID PRIMARY KEY,
    account_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    patient_id UUID NOT NULL REFERENCES patients(id) ON DELETE RESTRICT,
    case_ref TEXT NOT NULL
        CHECK (length(trim(case_ref)) BETWEEN 1 AND 256
            AND case_ref !~ '[[:space:]]'),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'archived', 'deleted')),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (account_id, case_ref)
);
CREATE INDEX IF NOT EXISTS cases_account_updated_idx
    ON cases (account_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS cases_patient_created_idx
    ON cases (patient_id, created_at DESC);

CREATE TABLE IF NOT EXISTS case_documents (
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    document_version INTEGER NOT NULL CHECK (document_version > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (case_id, document_id, document_version),
    FOREIGN KEY (document_id, document_version)
        REFERENCES document_versions(document_id, version)
        ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS case_documents_document_idx
    ON case_documents (document_id, document_version);

CREATE TABLE IF NOT EXISTS case_facts (
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    fact_id UUID NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (case_id, fact_id)
);
CREATE INDEX IF NOT EXISTS case_facts_fact_idx
    ON case_facts (fact_id);

CREATE TABLE IF NOT EXISTS fact_reviews (
    id UUID PRIMARY KEY,
    fact_id UUID NOT NULL REFERENCES facts(id) ON DELETE RESTRICT,
    case_id UUID REFERENCES cases(id) ON DELETE SET NULL,
    reviewer_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    decision TEXT NOT NULL
        CHECK (decision IN ('pending', 'confirmed', 'rejected', 'conflict')),
    confidence DOUBLE PRECISION NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    source_start INTEGER,
    source_end INTEGER,
    review_ref TEXT NOT NULL
        CHECK (length(trim(review_ref)) BETWEEN 1 AND 256
            AND review_ref !~ '[[:space:]]'),
    review_version INTEGER NOT NULL DEFAULT 1 CHECK (review_version > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (fact_id, review_version),
    UNIQUE (fact_id, review_ref),
    CHECK (source_start IS NULL OR source_start >= 0),
    CHECK (source_end IS NULL OR (source_start IS NOT NULL AND source_end >= source_start))
);
CREATE INDEX IF NOT EXISTS fact_reviews_fact_created_idx
    ON fact_reviews (fact_id, created_at DESC);
CREATE INDEX IF NOT EXISTS fact_reviews_case_created_idx
    ON fact_reviews (case_id, created_at DESC);

CREATE TABLE IF NOT EXISTS document_history (
    id UUID PRIMARY KEY,
    document_id UUID NOT NULL,
    document_version INTEGER NOT NULL CHECK (document_version > 0),
    actor_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL
        CHECK (event_type IN (
            'uploaded', 'processing_started', 'processing_succeeded',
            'processing_failed', 'reviewed', 'superseded', 'deleted'
        )),
    event_ref TEXT NOT NULL
        CHECK (length(trim(event_ref)) BETWEEN 1 AND 256
            AND event_ref !~ '[[:space:]]'),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(metadata) = 'object'),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (document_id, document_version)
        REFERENCES document_versions(document_id, version)
        ON DELETE RESTRICT,
    UNIQUE (document_id, document_version, event_type, event_ref)
);
CREATE INDEX IF NOT EXISTS document_history_document_time_idx
    ON document_history (document_id, recorded_at DESC);

CREATE TABLE IF NOT EXISTS account_history (
    id UUID PRIMARY KEY,
    account_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    event_type TEXT NOT NULL
        CHECK (event_type IN (
            'created', 'updated', 'signed_in', 'signed_out',
            'exported', 'share_created', 'share_revoked', 'deleted'
        )),
    event_ref TEXT NOT NULL
        CHECK (length(trim(event_ref)) BETWEEN 1 AND 256
            AND event_ref !~ '[[:space:]]'),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(metadata) = 'object'),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (account_id, event_type, event_ref)
);
CREATE INDEX IF NOT EXISTS account_history_account_time_idx
    ON account_history (account_id, recorded_at DESC);

CREATE TABLE IF NOT EXISTS case_history (
    id UUID PRIMARY KEY,
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE RESTRICT,
    actor_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL
        CHECK (event_type IN (
            'created', 'updated', 'document_attached', 'fact_reviewed',
            'summary_generated', 'shared', 'share_revoked', 'archived', 'deleted'
        )),
    event_ref TEXT NOT NULL
        CHECK (length(trim(event_ref)) BETWEEN 1 AND 256
            AND event_ref !~ '[[:space:]]'),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(metadata) = 'object'),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (case_id, event_type, event_ref)
);
CREATE INDEX IF NOT EXISTS case_history_case_time_idx
    ON case_history (case_id, recorded_at DESC);

CREATE OR REPLACE FUNCTION prevent_history_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'append-only history records cannot be updated or deleted';
END;
$$;

DROP TRIGGER IF EXISTS fact_reviews_append_only ON fact_reviews;
CREATE TRIGGER fact_reviews_append_only
    BEFORE UPDATE OR DELETE ON fact_reviews
    FOR EACH ROW EXECUTE FUNCTION prevent_history_mutation();

DROP TRIGGER IF EXISTS document_history_append_only ON document_history;
CREATE TRIGGER document_history_append_only
    BEFORE UPDATE OR DELETE ON document_history
    FOR EACH ROW EXECUTE FUNCTION prevent_history_mutation();

DROP TRIGGER IF EXISTS account_history_append_only ON account_history;
CREATE TRIGGER account_history_append_only
    BEFORE UPDATE OR DELETE ON account_history
    FOR EACH ROW EXECUTE FUNCTION prevent_history_mutation();

DROP TRIGGER IF EXISTS case_history_append_only ON case_history;
CREATE TRIGGER case_history_append_only
    BEFORE UPDATE OR DELETE ON case_history
    FOR EACH ROW EXECUTE FUNCTION prevent_history_mutation();

COMMIT;
