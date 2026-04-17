-- Migration 041: Hybrid Retrieval — tsvector column + GIN index + trigger
-- Adds full-text search capability to rag_chunks for hybrid dense+sparse retrieval.

-- Add tsvector column to rag_chunks
ALTER TABLE rag_chunks ADD COLUMN IF NOT EXISTS tsv tsvector;

-- Backfill existing chunks with tsvector data
UPDATE rag_chunks SET tsv = to_tsvector('english', COALESCE(text, '')) WHERE tsv IS NULL;

-- Create GIN index for efficient full-text search
CREATE INDEX IF NOT EXISTS idx_rag_chunks_tsv ON rag_chunks USING GIN (tsv);

-- Trigger function to auto-update tsvector on insert/update
CREATE OR REPLACE FUNCTION rag_chunks_tsv_trigger() RETURNS trigger AS $$
BEGIN
    NEW.tsv := to_tsvector('english', COALESCE(NEW.text, ''));
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_rag_chunks_tsv ON rag_chunks;
CREATE TRIGGER trg_rag_chunks_tsv
    BEFORE INSERT OR UPDATE OF text ON rag_chunks
    FOR EACH ROW EXECUTE FUNCTION rag_chunks_tsv_trigger();
