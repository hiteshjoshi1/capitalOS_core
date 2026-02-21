DO $$ BEGIN
  CREATE TYPE import_status AS ENUM (
    'UPLOADED',
    'IDENTIFIED',
    'PARSED',
    'VALIDATED',
    'IMPORTED',
    'NEEDS_MAPPING',
    'FAILED'
  );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS import_jobs (
  id BIGSERIAL PRIMARY KEY,
  account_id BIGINT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  platform TEXT NOT NULL,
  original_filename TEXT NOT NULL,
  stored_path TEXT NOT NULL,
  file_sha256 TEXT NOT NULL,
  format_signature TEXT,
  parser_key TEXT,
  status import_status NOT NULL DEFAULT 'UPLOADED',
  report_path TEXT,
  error_message TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_import_jobs_file_sha256 ON import_jobs(file_sha256);
CREATE INDEX IF NOT EXISTS idx_import_jobs_signature ON import_jobs(format_signature);
CREATE INDEX IF NOT EXISTS idx_import_jobs_account_created ON import_jobs(account_id, created_at);

CREATE TABLE IF NOT EXISTS parser_registry (
  id BIGSERIAL PRIMARY KEY,
  format_signature TEXT NOT NULL UNIQUE,
  parser_key TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
