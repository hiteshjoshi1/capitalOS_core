-- Migration 045: Add selective_options JSON column to rag_sources
-- Stores deterministic selective-ingestion rules (start_after, stop_before,
-- include_headings, exclude_sections) that were applied when a source was
-- ingested. NULL means no selective filtering was applied (full source ingested).

ALTER TABLE rag_sources
    ADD COLUMN IF NOT EXISTS selective_options JSONB;
