-- Migration 051: remove persisted raw/clean text from rag_sources and rag_documents.
-- Preserve document char_count in metadata_json before dropping the storage columns.

UPDATE rag_documents
SET metadata_json = jsonb_set(
    COALESCE(metadata_json, '{}'::jsonb),
    '{char_count}',
    to_jsonb(length(COALESCE(clean_text, ''))),
    true
);

ALTER TABLE rag_documents
    DROP COLUMN IF EXISTS raw_text;

ALTER TABLE rag_documents
    DROP COLUMN IF EXISTS clean_text;

ALTER TABLE rag_sources
    DROP COLUMN IF EXISTS raw_text;

ALTER TABLE rag_sources
    DROP COLUMN IF EXISTS clean_text;
