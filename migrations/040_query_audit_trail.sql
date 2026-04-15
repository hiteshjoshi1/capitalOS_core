-- Migration 040: Query audit trail and retrieval evaluation harness
-- Creates rag_queries, rag_query_evidence, and rag_eval_golden tables.

-- Query log: one row per user query
CREATE TABLE IF NOT EXISTS rag_queries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query_text TEXT NOT NULL,
    mode VARCHAR(64),
    intent_json JSONB,
    retrieval_config JSONB,
    answer_text TEXT,
    latency_ms INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Evidence log: links each query to the chunks that were retrieved
CREATE TABLE IF NOT EXISTS rag_query_evidence (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query_id UUID NOT NULL REFERENCES rag_queries(id) ON DELETE CASCADE,
    chunk_id UUID NOT NULL REFERENCES rag_chunks(id) ON DELETE CASCADE,
    rank INTEGER NOT NULL,
    cosine_distance FLOAT,
    reranker_score FLOAT,
    rrf_score FLOAT,
    ts_rank FLOAT,
    is_golden BOOLEAN DEFAULT FALSE
);

-- Golden dataset: curated query-passage pairs for offline evaluation
CREATE TABLE IF NOT EXISTS rag_eval_golden (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query_text TEXT NOT NULL,
    chunk_id UUID NOT NULL REFERENCES rag_chunks(id) ON DELETE CASCADE,
    relevance_grade INTEGER NOT NULL DEFAULT 1,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for common access patterns
CREATE INDEX IF NOT EXISTS idx_rag_query_evidence_query_id ON rag_query_evidence(query_id);
CREATE INDEX IF NOT EXISTS idx_rag_query_evidence_chunk_id ON rag_query_evidence(chunk_id);
CREATE INDEX IF NOT EXISTS idx_rag_eval_golden_query_text ON rag_eval_golden(query_text);
CREATE INDEX IF NOT EXISTS idx_rag_queries_created_at ON rag_queries(created_at);
