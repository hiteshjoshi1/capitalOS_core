-- Card payment due dates (#352, D-91): what one card statement says is due, and by when.
--
-- One row per card statement: its date, the payment due date, what it says is owed and the
-- minimum payment. `source`: 'statement' (read from an uploaded statement by its parser,
-- with the upload's import_job_id, removed when the upload is) or 'manual' (typed in from the
-- statement by the card's owner on Liabilities -> Card balances). Never a guessed date: a card
-- with no row has no known due date. app/valuation/card_dues.py turns the newest row into the
-- Inbox reminder (5 days before, overdue after) until the card's payments since the statement
-- cover what it says is owed.
CREATE TABLE IF NOT EXISTS card_statement_dues (
  id BIGSERIAL PRIMARY KEY,
  account_id BIGINT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  statement_date DATE NOT NULL,
  due_date DATE NOT NULL,
  amount_due NUMERIC(38, 2),
  minimum_due NUMERIC(38, 2),
  source TEXT NOT NULL CHECK (source IN ('statement', 'manual')),
  import_job_id BIGINT REFERENCES import_jobs(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT card_statement_dues_due_after_statement CHECK (due_date >= statement_date),
  CONSTRAINT card_statement_dues_one_per_statement UNIQUE (account_id, statement_date)
);

CREATE INDEX IF NOT EXISTS card_statement_dues_import_job_idx ON card_statement_dues (import_job_id);
