-- Migration 046: Add deterministic fanout/audit metadata for RAG ingestion

ALTER TABLE rag_sources
    ADD COLUMN IF NOT EXISTS ingestion_config JSONB;

ALTER TABLE rag_sources
    ADD COLUMN IF NOT EXISTS raw_text TEXT;

ALTER TABLE rag_sources
    ADD COLUMN IF NOT EXISTS clean_text TEXT;

ALTER TABLE rag_documents
    ADD COLUMN IF NOT EXISTS author_id TEXT REFERENCES rag_authors(id) ON DELETE SET NULL;

ALTER TABLE rag_documents
    ADD COLUMN IF NOT EXISTS parent_document_id UUID REFERENCES rag_documents(id) ON DELETE SET NULL;

ALTER TABLE rag_documents
    ADD COLUMN IF NOT EXISTS source_document_index INTEGER NOT NULL DEFAULT 0;

ALTER TABLE rag_documents
    ADD COLUMN IF NOT EXISTS publication_year INTEGER;

ALTER TABLE rag_documents
    ADD COLUMN IF NOT EXISTS venue TEXT;

ALTER TABLE rag_documents
    ADD COLUMN IF NOT EXISTS collection TEXT;

ALTER TABLE rag_documents
    ADD COLUMN IF NOT EXISTS canonical_work_id TEXT;

ALTER TABLE rag_documents
    ADD COLUMN IF NOT EXISTS canonical_status TEXT;

ALTER TABLE rag_documents
    ADD COLUMN IF NOT EXISTS dedupe_priority INTEGER;

ALTER TABLE rag_documents
    ADD COLUMN IF NOT EXISTS source_section TEXT;

ALTER TABLE rag_documents
    ADD COLUMN IF NOT EXISTS note_taker TEXT;

ALTER TABLE rag_documents
    ADD COLUMN IF NOT EXISTS work_type TEXT;

ALTER TABLE rag_documents
    ADD COLUMN IF NOT EXISTS metadata_json JSONB NOT NULL DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_rag_documents_author_id
    ON rag_documents (author_id);

CREATE INDEX IF NOT EXISTS idx_rag_documents_parent_document_id
    ON rag_documents (parent_document_id);

CREATE INDEX IF NOT EXISTS idx_rag_documents_source_document_index
    ON rag_documents (source_id, source_document_index);
