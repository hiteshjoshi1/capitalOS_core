-- Uploads: refuse a statement sent to the wrong account, and undo an upload (#180).

-- A refused upload (wrong account type, or a statement naming another account)
-- keeps its job row as REJECTED; a removed upload keeps its job row as REMOVED.
-- The new values are not used in this migration, so adding them inside its
-- transaction is fine (Postgres 12+).
ALTER TYPE import_status ADD VALUE IF NOT EXISTS 'REJECTED';
ALTER TYPE import_status ADD VALUE IF NOT EXISTS 'REMOVED';

-- Which upload inserted each transaction. Rows imported before this migration
-- keep NULL, and their jobs can't be removed (their rows can't be told apart).
ALTER TABLE transactions
  ADD COLUMN IF NOT EXISTS import_job_id BIGINT REFERENCES import_jobs(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_transactions_import_job
  ON transactions(import_job_id) WHERE import_job_id IS NOT NULL;

-- Which upload a canonical holdings import run came from.
ALTER TABLE broker_import_runs
  ADD COLUMN IF NOT EXISTS import_job_id BIGINT REFERENCES import_jobs(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_broker_import_runs_import_job
  ON broker_import_runs(import_job_id) WHERE import_job_id IS NOT NULL;

-- What removing the upload needs to put back: rows its writes replaced (an
-- earlier balance for the same date, earlier holdings for the same date), card
-- limits before it, authority windows it created. NULL for jobs that ran before
-- this migration: those can't be removed.
ALTER TABLE import_jobs ADD COLUMN IF NOT EXISTS undo_json JSONB;
ALTER TABLE import_jobs ADD COLUMN IF NOT EXISTS removed_at TIMESTAMPTZ;

-- The statement account each account's uploads name: a hash of the normalised
-- number and its last four digits, never the number itself.
CREATE TABLE IF NOT EXISTS account_statement_identities (
  account_id     BIGINT PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
  identity_hash  TEXT NOT NULL,
  last4          TEXT NOT NULL,
  parser_key     TEXT,
  import_job_id  BIGINT REFERENCES import_jobs(id) ON DELETE SET NULL,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_account_statement_identities_hash
  ON account_statement_identities(identity_hash);
