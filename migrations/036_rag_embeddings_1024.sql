-- Migration 036: Move RAG embeddings to 1024 dimensions for Voyage-4
--
-- Existing RAG vectors are currently disposable/mock. Recreate only the
-- rag_embeddings table and ANN index so document/chunk metadata remains intact.

DROP INDEX IF EXISTS idx_rag_embeddings_vector;
DROP TABLE IF EXISTS rag_embeddings;

CREATE TABLE rag_embeddings (
    chunk_id        UUID PRIMARY KEY REFERENCES rag_chunks(id) ON DELETE CASCADE,
    embedding       VECTOR(1024) NOT NULL,
    model           TEXT NOT NULL DEFAULT 'voyage-4',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_rag_embeddings_vector
    ON rag_embeddings
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 50);
