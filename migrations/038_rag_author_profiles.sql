-- Migration 038: Author wisdom profiles for RAG intelligence retrieval
-- Adds persisted author wisdom artifacts generated from the ingested corpus.

CREATE TABLE rag_author_profiles (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    author_id       TEXT NOT NULL REFERENCES rag_authors(id) ON DELETE CASCADE,
    worldview       TEXT,
    key_maxims      TEXT[] NOT NULL DEFAULT '{}',
    strengths       TEXT[] NOT NULL DEFAULT '{}',
    weaknesses      TEXT[] NOT NULL DEFAULT '{}',
    favored_decision_variables  TEXT[] NOT NULL DEFAULT '{}',
    anti_patterns   TEXT[] NOT NULL DEFAULT '{}',
    generation_model TEXT NOT NULL DEFAULT 'template',
    corpus_chunk_count INTEGER NOT NULL DEFAULT 0,
    generated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (author_id)
);

CREATE TABLE rag_author_profile_citations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id      UUID NOT NULL REFERENCES rag_author_profiles(id) ON DELETE CASCADE,
    chunk_id        UUID NOT NULL REFERENCES rag_chunks(id) ON DELETE CASCADE,
    citation_context TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_rag_author_profiles_author ON rag_author_profiles (author_id);
CREATE INDEX idx_rag_profile_citations_profile ON rag_author_profile_citations (profile_id);
CREATE INDEX idx_rag_profile_citations_chunk ON rag_author_profile_citations (chunk_id);
