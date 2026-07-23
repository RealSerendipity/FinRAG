-- Wave 1: initial schema. Idempotent — safe to run multiple times.
CREATE EXTENSION IF NOT EXISTS vector;

-- Trigger function: set updated_at only when a table-specific trigger detects a real update.
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

CREATE TABLE IF NOT EXISTS companies (
    id         BIGSERIAL   PRIMARY KEY,
    ticker     TEXT        NOT NULL,
    cik        BIGINT,
    name       TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ,
    CONSTRAINT companies_ticker_uq UNIQUE (ticker)
);

CREATE OR REPLACE TRIGGER companies_updated_at
    BEFORE UPDATE ON companies
    FOR EACH ROW
    WHEN (
        OLD.ticker IS DISTINCT FROM NEW.ticker
        OR OLD.cik IS DISTINCT FROM NEW.cik
        OR OLD.name IS DISTINCT FROM NEW.name
    )
    EXECUTE FUNCTION set_updated_at();

-- filing_types is a small reference table for SEC form codes.
CREATE TABLE IF NOT EXISTS filing_types (
    id          BIGSERIAL   PRIMARY KEY,
    code        TEXT        NOT NULL,
    description TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ,
    CONSTRAINT filing_types_code_uq UNIQUE (code)
);

CREATE OR REPLACE TRIGGER filing_types_updated_at
    BEFORE UPDATE ON filing_types
    FOR EACH ROW
    WHEN (
        OLD.code IS DISTINCT FROM NEW.code
        OR OLD.description IS DISTINCT FROM NEW.description
    )
    EXECUTE FUNCTION set_updated_at();

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
    period         DATE        NOT NULL,
    filed_at       DATE,
    accession      TEXT        UNIQUE NOT NULL,
    raw_url        TEXT,
    metadata       JSONB       DEFAULT '{}'::jsonb,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ
);

CREATE OR REPLACE TRIGGER documents_updated_at
    BEFORE UPDATE ON documents
    FOR EACH ROW
    WHEN (
        OLD.company_id IS DISTINCT FROM NEW.company_id
        OR OLD.filing_type_id IS DISTINCT FROM NEW.filing_type_id
        OR OLD.period IS DISTINCT FROM NEW.period
        OR OLD.filed_at IS DISTINCT FROM NEW.filed_at
        OR OLD.accession IS DISTINCT FROM NEW.accession
        OR OLD.raw_url IS DISTINCT FROM NEW.raw_url
        OR OLD.metadata IS DISTINCT FROM NEW.metadata
    )
    EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS chunks (
    id          BIGSERIAL   PRIMARY KEY,
    document_id BIGINT      NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    section     TEXT,
    chunk_index INT         NOT NULL,
    content     TEXT        NOT NULL,
    tokens      INT,
    embedding   VECTOR(1024),
    tsv         TSVECTOR    GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    metadata    JSONB       DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ
);

CREATE OR REPLACE TRIGGER chunks_updated_at
    BEFORE UPDATE ON chunks
    FOR EACH ROW
    WHEN (
        OLD.document_id IS DISTINCT FROM NEW.document_id
        OR OLD.section IS DISTINCT FROM NEW.section
        OR OLD.chunk_index IS DISTINCT FROM NEW.chunk_index
        OR OLD.content IS DISTINCT FROM NEW.content
        OR OLD.tokens IS DISTINCT FROM NEW.tokens
        OR OLD.embedding::text IS DISTINCT FROM NEW.embedding::text
        OR OLD.metadata IS DISTINCT FROM NEW.metadata
    )
    EXECUTE FUNCTION set_updated_at();

CREATE INDEX IF NOT EXISTS chunks_doc_idx        ON chunks (document_id);
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_tsv_gin        ON chunks USING GIN (tsv);
CREATE INDEX IF NOT EXISTS companies_ticker_idx         ON companies (ticker);
CREATE INDEX IF NOT EXISTS documents_company_period_idx ON documents (company_id, period);
