-- Backfill legacy RAG documents that were created without a document-level
-- author_id even though the owning source already has one.
--
-- Keep document-level overrides intact by only updating rows where
-- rag_documents.author_id is currently NULL.

UPDATE rag_documents AS rd
SET author_id = rs.author_id
FROM rag_sources AS rs
WHERE rd.source_id = rs.id
  AND rd.author_id IS NULL
  AND rs.author_id IS NOT NULL;
