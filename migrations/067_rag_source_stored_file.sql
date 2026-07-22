-- Manually-uploaded PDFs (the "Upload PDF instead" / "Upload PDF directly"
-- fallback for sources the automatic fetcher can't reach, e.g. bot-blocked
-- hosts) were previously discarded after parsing: only the extracted text
-- was kept, so there was no way to actually open/read the file afterward.
-- Store the raw bytes so we can serve them back through our own endpoint,
-- independent of whether the original host is reachable.
ALTER TABLE rag_sources
    ADD COLUMN IF NOT EXISTS stored_file_bytes BYTEA,
    ADD COLUMN IF NOT EXISTS stored_file_content_type TEXT,
    ADD COLUMN IF NOT EXISTS stored_file_filename TEXT;
