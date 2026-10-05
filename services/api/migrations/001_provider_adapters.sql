-- Provider adapter schema for staging PostgreSQL.
-- Payloads are canonical JSON generated from the provider-neutral dataclasses.
-- Do not store access tokens, document bytes, or raw credentials in these tables.

CREATE TABLE IF NOT EXISTS metadata_resources (
    resource_type TEXT NOT NULL,
    identifier TEXT NOT NULL,
    owner_id TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL CHECK (version >= 1),
    payload JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (resource_type, identifier)
);

CREATE INDEX IF NOT EXISTS metadata_resources_owner_idx
    ON metadata_resources (owner_id, resource_type, updated_at DESC);

CREATE TABLE IF NOT EXISTS audit_events (
    identifier TEXT PRIMARY KEY,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS audit_events_created_idx
    ON audit_events (created_at, identifier);

CREATE TABLE IF NOT EXISTS idempotency (
    actor_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (actor_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idempotency_created_idx
    ON idempotency (created_at);
