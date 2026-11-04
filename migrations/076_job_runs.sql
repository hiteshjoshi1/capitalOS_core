-- Job status (#156): one row per finished run of a scheduled or manual data job,
-- per scope (an IBKR account, an exchange, a crypto wallet, or 'all').
--
-- "Done" means the data advanced: `status` says whether the run left the data as
-- current as it should be, `data_advanced` whether it moved the data forward, and
-- `data_as_of` is how current the data is after the run (ISO-8601 date or
-- timestamp text, the job's own unit: a statement date, a trade date, a fetch
-- time). `attempt` counts consecutive failed runs of the same (job, scope)
-- including this one (1 after a non-failed run), so the Data Hub reads a
-- failure streak from the newest row alone.
--
-- `error_summary` is scrubbed before it is stored (app/core/job_runs.py): no
-- URLs, tokens, addresses or account numbers. `scope` uses internal ids only.
--
-- The existing run tables (broker_import_runs, market_data_runs, crypto wallet
-- snapshots) stay as they are; this table is the cross-job status view.
CREATE TABLE IF NOT EXISTS job_runs (
  id BIGSERIAL PRIMARY KEY,
  job TEXT NOT NULL,
  scope TEXT NOT NULL DEFAULT 'all',
  user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
  trigger TEXT NOT NULL CHECK (trigger IN ('scheduled', 'manual')),
  status TEXT NOT NULL CHECK (status IN ('success', 'partial', 'no_new_data', 'failed')),
  started_at TIMESTAMPTZ NOT NULL,
  finished_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  data_advanced BOOLEAN NOT NULL DEFAULT FALSE,
  data_as_of TEXT,
  error_summary TEXT,
  attempt INTEGER NOT NULL DEFAULT 1,
  details JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_job_runs_job_scope_finished
  ON job_runs(job, scope, finished_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_job_runs_user_job
  ON job_runs(user_id, job, finished_at DESC);
