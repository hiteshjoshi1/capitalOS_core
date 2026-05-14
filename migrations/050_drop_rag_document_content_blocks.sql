-- Migration 050: remove structured reader payload persistence from rag_documents

ALTER TABLE rag_documents
    DROP COLUMN IF EXISTS content_blocks_json;

-- Down migration guidance (manual, reversible in normal workflow):
-- ALTER TABLE rag_documents ADD COLUMN content_blocks_json JSONB;