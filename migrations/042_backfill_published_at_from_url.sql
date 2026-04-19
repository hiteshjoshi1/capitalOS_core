-- Backfill rag_documents.published_at and rag_chunks.metadata_json.year
-- from source URL patterns.
--
-- Buffett letters: /letters/YYYY.html or /letters/YYYYltr.pdf
-- This also sets metadata_json.year on chunks for fallback date filtering.

-- Step 1: Backfill rag_documents.published_at from rag_sources.url
UPDATE rag_documents rd
SET published_at = make_date(
    (regexp_match(rs.url, '/letters/(\d{4})'))[1]::int,
    1, 1
)
FROM rag_sources rs
WHERE rd.source_id = rs.id
  AND rd.published_at IS NULL
  AND rs.url ~ '/letters/\d{4}';

-- Step 2: Backfill rag_chunks.metadata_json.year from the document published_at
UPDATE rag_chunks rc
SET metadata_json = rc.metadata_json || jsonb_build_object(
    'year', EXTRACT(YEAR FROM rd.published_at)::int,
    'published_at', rd.published_at::text
)
FROM rag_documents rd
WHERE rc.document_id = rd.id
  AND rd.published_at IS NOT NULL
  AND (rc.metadata_json->>'year') IS NULL;

-- Step 3: Also backfill rag_documents.title from URL when empty
UPDATE rag_documents rd
SET title = 'Berkshire Hathaway Shareholder Letter ' || EXTRACT(YEAR FROM rd.published_at)::int
WHERE rd.published_at IS NOT NULL
  AND (rd.title IS NULL OR rd.title = '');
