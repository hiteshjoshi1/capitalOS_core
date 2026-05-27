-- Migration 054: Corpus-local expansion index for RAG retrieval (Issue 171).
-- Stores precomputed NPMI-based expansion terms per (author, pivot_type, pivot_id).

CREATE TABLE IF NOT EXISTS rag_corpus_expansions (
  author_id        TEXT NOT NULL REFERENCES rag_authors(id) ON DELETE CASCADE,
  pivot_type       TEXT NOT NULL CHECK (pivot_type IN ('entity','concept')),
  pivot_id         TEXT NOT NULL,  -- entity_id or concept_id depending on pivot_type
  expansion_term   TEXT NOT NULL,  -- lowercase normalized term or phrase
  expansion_type   TEXT NOT NULL CHECK (expansion_type IN ('entity','concept','phrase')),
  expansion_ref_id TEXT,           -- set when expansion_type is 'entity' or 'concept'
  support_count    INT  NOT NULL,
  npmi             REAL NOT NULL,
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (author_id, pivot_type, pivot_id, expansion_term)
);

CREATE INDEX IF NOT EXISTS rag_corpus_expansions_author_pivot
  ON rag_corpus_expansions(author_id, pivot_type, pivot_id);
