CREATE TABLE IF NOT EXISTS ingest_batches (
    id                   UUID        PRIMARY KEY,
    idempotency_key      TEXT        NOT NULL UNIQUE,
    request_fingerprint  TEXT        NOT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ingest_batches_idempotency_key_ck
        CHECK (char_length(idempotency_key) BETWEEN 8 AND 128),
    CONSTRAINT ingest_batches_fingerprint_ck
        CHECK (char_length(request_fingerprint) = 64)
);

CREATE TABLE IF NOT EXISTS ingest_jobs (
    id                 UUID             PRIMARY KEY,
    batch_id           UUID             NOT NULL,
    ticker             TEXT             NOT NULL,
    form_type          TEXT             NOT NULL,
    year               INT,
    period             TEXT,
    status             TEXT             NOT NULL DEFAULT 'queued',
    attempts           INT              NOT NULL DEFAULT 0,
    claim_token        UUID,
    qstash_message_id  TEXT,
    chunks             INT,
    elapsed_s          DOUBLE PRECISION,
    error_code         TEXT,
    error_message      TEXT,
    created_at         TIMESTAMPTZ      NOT NULL DEFAULT now(),
    started_at         TIMESTAMPTZ,
    finished_at        TIMESTAMPTZ,
    updated_at         TIMESTAMPTZ      NOT NULL DEFAULT now(),
    CONSTRAINT ingest_jobs_status_ck
        CHECK (status IN ('queued', 'running', 'retrying', 'done', 'error')),
    CONSTRAINT ingest_jobs_scope_ck
        CHECK (year IS NOT NULL OR period IS NOT NULL)
);

ALTER TABLE ingest_jobs
    ADD COLUMN IF NOT EXISTS claim_token UUID;

CREATE INDEX IF NOT EXISTS ingest_jobs_batch_idx
    ON ingest_jobs (batch_id, created_at);

CREATE INDEX IF NOT EXISTS ingest_jobs_status_idx
    ON ingest_jobs (status, updated_at);
