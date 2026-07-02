-- Migration 058: Attach HTTP request correlation IDs to RAG query audit rows.

ALTER TABLE rag_queries
    ADD COLUMN IF NOT EXISTS request_id VARCHAR(128);

CREATE INDEX IF NOT EXISTS idx_rag_queries_request_id ON rag_queries(request_id);
