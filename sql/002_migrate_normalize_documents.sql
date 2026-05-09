-- Wave 1c migration: normalize documents table (ticker/filing_type → FK references).
-- Idempotent — safe to run on already-migrated databases or fresh installs.

DO $$
BEGIN
    -- Guard: only run when the old denormalized 'ticker' column still exists.
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'documents' AND column_name = 'ticker'
    ) THEN

        -- 1. Backfill companies from distinct tickers found in documents.
        INSERT INTO companies (ticker, cik, name)
        SELECT DISTINCT ticker, NULL, ticker
        FROM documents
        ON CONFLICT (ticker) DO NOTHING;

        -- 2. Add new FK columns as nullable so rows can be populated before constraints apply.
        ALTER TABLE documents
            ADD COLUMN IF NOT EXISTS company_id     BIGINT REFERENCES companies(id)    ON DELETE RESTRICT,
            ADD COLUMN IF NOT EXISTS filing_type_id BIGINT REFERENCES filing_types(id) ON DELETE RESTRICT;

        -- 3. Resolve company_id for every existing row.
        UPDATE documents d
        SET company_id = c.id
        FROM companies c
        WHERE c.ticker = d.ticker;

        -- 4. Resolve filing_type_id for every existing row.
        UPDATE documents d
        SET filing_type_id = ft.id
        FROM filing_types ft
        WHERE ft.code = d.filing_type;

        -- 5. Enforce NOT NULL now that all rows have been populated.
        ALTER TABLE documents
            ALTER COLUMN company_id     SET NOT NULL,
            ALTER COLUMN filing_type_id SET NOT NULL;

        -- 6. Remove the old denormalized columns.
        ALTER TABLE documents
            DROP COLUMN IF EXISTS ticker,
            DROP COLUMN IF EXISTS filing_type;

        -- 7. Replace the old index (was on ticker/period) with the normalized equivalent.
        DROP INDEX IF EXISTS documents_lookup_idx;
        CREATE INDEX IF NOT EXISTS documents_company_period_idx ON documents (company_id, period);
        CREATE INDEX IF NOT EXISTS companies_ticker_idx         ON companies (ticker);

    END IF;
END $$;
