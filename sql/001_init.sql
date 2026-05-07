-- Wave 1a: initial schema. Idempotent — safe to run multiple times.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id          BIGSERIAL PRIMARY KEY,
    ticker      TEXT        NOT NULL,
    filing_type TEXT        NOT NULL,
    period      TEXT        NOT NULL,
    filed_at    DATE,
    accession   TEXT        UNIQUE NOT NULL,
    raw_url     TEXT,
    metadata    JSONB       DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
    id          BIGSERIAL PRIMARY KEY,
    document_id BIGINT      NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    section     TEXT,
    chunk_index INT         NOT NULL,
    content     TEXT        NOT NULL,
    tokens      INT,
    embedding   VECTOR(1024),
    tsv         TSVECTOR    GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    metadata    JSONB       DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS chunks_doc_idx        ON chunks (document_id);
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_tsv_gin        ON chunks USING GIN (tsv);
CREATE INDEX IF NOT EXISTS documents_lookup_idx  ON documents (ticker, period);
