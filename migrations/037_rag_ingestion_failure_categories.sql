-- Migration 037: Add explicit failure classification for RAG ingestion jobs

ALTER TABLE rag_ingestion_jobs
    ADD COLUMN IF NOT EXISTS failure_category TEXT;
