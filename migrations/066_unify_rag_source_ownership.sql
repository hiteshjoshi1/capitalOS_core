-- The research corpus (author sources/documents) was ingested under a mix of
-- user_id=1 (demo), user_id=2 (hitesh), and NULL ownership depending on which
-- account happened to be logged in at ingestion time. That split hid authors
-- (e.g. Charlie Munger, Nick Sleep) from whichever account wasn't the one
-- that ingested them. Unify all of it under hitesh's account (user_id=2),
-- the single real operator of this instance.
UPDATE rag_sources
SET user_id = 2
WHERE user_id IS DISTINCT FROM 2;

UPDATE rag_ingestion_jobs
SET user_id = 2
WHERE user_id IS DISTINCT FROM 2;

UPDATE realtime_events
SET user_id = 2
WHERE topic = 'author-ingestion'
  AND user_id IS DISTINCT FROM 2;
