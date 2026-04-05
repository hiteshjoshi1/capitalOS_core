-- Migration 035: RAG Phase 1 — pgvector + thinker ingestion foundation
-- Enables the pgvector extension and creates all Phase 1 RAG tables.
-- Must run AFTER 034_enforce_accounts_user_ownership.sql.

-- ─────────────────────────────────────────────────────────────────────────────
-- Extension
-- ─────────────────────────────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS vector;

-- ─────────────────────────────────────────────────────────────────────────────
-- Author registry
-- Populated from config/rag_authors.yaml via POST /rag/authors/sync-config.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE rag_authors (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    domains         TEXT[] NOT NULL DEFAULT '{}',
    expertise_tags  TEXT[] NOT NULL DEFAULT '{}',
    overall_weight  FLOAT NOT NULL DEFAULT 1.0,
    role_type       TEXT,
    config_source   TEXT NOT NULL DEFAULT 'config/rag_authors.yaml',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Author reasoning card
-- Preserves lens-adapter config for future query-time author selection.
-- Not executed in Phase 1 but must be stored now.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE rag_author_cards (
    author_id       TEXT PRIMARY KEY REFERENCES rag_authors(id) ON DELETE CASCADE,
    focus_areas     TEXT[] NOT NULL DEFAULT '{}',
    avoid_patterns  TEXT[] NOT NULL DEFAULT '{}',
    biases          TEXT[] NOT NULL DEFAULT '{}',
    prompt_adapter  JSONB NOT NULL DEFAULT '{}',
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Source registry
-- One row per URL or manual-upload source.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE rag_sources (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    author_id       TEXT NOT NULL REFERENCES rag_authors(id) ON DELETE CASCADE,
    url             TEXT,
    source_type     TEXT NOT NULL,          -- html | pdf | text | manual
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending | fetched | failed | ingested
    hash            TEXT,                   -- SHA-256 of raw content for dedup
    last_ingested_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Documents
-- One parsed document per source (1-to-1 for now, reserved for multi-doc sources).
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE rag_documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id       UUID NOT NULL REFERENCES rag_sources(id) ON DELETE CASCADE,
    title           TEXT,
    published_at    DATE,
    raw_text        TEXT,
    clean_text      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Chunks
-- Fixed-size token windows with overlap, derived from clean_text.
-- metadata_json carries citation-ready lineage.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE rag_chunks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id     UUID NOT NULL REFERENCES rag_documents(id) ON DELETE CASCADE,
    chunk_index     INTEGER NOT NULL,
    text            TEXT NOT NULL,
    token_count     INTEGER,
    metadata_json   JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Embeddings
-- 1024-dimensional vector (voyage-4 default indexed text embedding output size).
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE rag_embeddings (
    chunk_id        UUID PRIMARY KEY REFERENCES rag_chunks(id) ON DELETE CASCADE,
    embedding       VECTOR(1024) NOT NULL,
    model           TEXT NOT NULL DEFAULT 'voyage-4',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Ingestion jobs
-- Tracks per-source ingestion attempts with status and error capture.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE rag_ingestion_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id       UUID NOT NULL REFERENCES rag_sources(id) ON DELETE CASCADE,
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending | running | done | failed
    failure_category TEXT,
    error           TEXT,
    stats_json      JSONB NOT NULL DEFAULT '{}',
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Indexes
-- ─────────────────────────────────────────────────────────────────────────────

-- ANN index for cosine similarity search (adjust lists for data size)
CREATE INDEX idx_rag_embeddings_vector
    ON rag_embeddings
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 50);

CREATE INDEX idx_rag_chunks_document ON rag_chunks (document_id);
CREATE INDEX idx_rag_chunks_metadata ON rag_chunks USING gin (metadata_json);
CREATE INDEX idx_rag_sources_author ON rag_sources (author_id);
CREATE INDEX idx_rag_sources_status ON rag_sources (status);
CREATE INDEX idx_rag_documents_source ON rag_documents (source_id);
CREATE INDEX idx_rag_jobs_source ON rag_ingestion_jobs (source_id);
CREATE INDEX idx_rag_jobs_status ON rag_ingestion_jobs (status);
