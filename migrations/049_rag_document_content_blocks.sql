-- Migration 049: persist structured reader content for RAG documents

ALTER TABLE rag_documents
    ADD COLUMN IF NOT EXISTS content_blocks_json JSONB;

-- Down migration guidance (manual, reversible in normal workflow):
-- ALTER TABLE rag_documents DROP COLUMN IF EXISTS content_blocks_json;
