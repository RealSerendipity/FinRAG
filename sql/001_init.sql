-- Wave 1: initial schema. Idempotent — safe to run multiple times.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS companies (
    id         BIGSERIAL   PRIMARY KEY,
    ticker     TEXT        NOT NULL,
    cik        BIGINT,
    name       TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT companies_ticker_uq UNIQUE (ticker)
);

-- filing_types is a small reference table for SEC form codes.
CREATE TABLE IF NOT EXISTS filing_types (
    id          BIGSERIAL   PRIMARY KEY,
    code        TEXT        NOT NULL,
    description TEXT,
    created_at  TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT filing_types_code_uq UNIQUE (code)
);

INSERT INTO filing_types (code, description) VALUES
    ('10-K',    'Annual report'),
    ('10-Q',    'Quarterly report'),
    ('8-K',     'Current report / material events'),
    ('20-F',    'Annual report for foreign private issuers'),
    ('DEF 14A', 'Proxy statement')
ON CONFLICT (code) DO NOTHING;

CREATE TABLE IF NOT EXISTS documents (
    id             BIGSERIAL   PRIMARY KEY,
    company_id     BIGINT      NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
    filing_type_id BIGINT      NOT NULL REFERENCES filing_types(id) ON DELETE RESTRICT,
    period         TEXT        NOT NULL,
    filed_at       DATE,
    accession      TEXT        UNIQUE NOT NULL,
    raw_url        TEXT,
    metadata       JSONB       DEFAULT '{}'::jsonb,
    created_at     TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
    id          BIGSERIAL PRIMARY KEY,
    document_id BIGINT    NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    section     TEXT,
    chunk_index INT       NOT NULL,
    content     TEXT      NOT NULL,
    tokens      INT,
    embedding   VECTOR(1024),
    tsv         TSVECTOR  GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    metadata    JSONB     DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS chunks_doc_idx        ON chunks (document_id);
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_tsv_gin        ON chunks USING GIN (tsv);
CREATE INDEX IF NOT EXISTS companies_ticker_idx         ON companies (ticker);
CREATE INDEX IF NOT EXISTS documents_company_period_idx ON documents (company_id, period);
