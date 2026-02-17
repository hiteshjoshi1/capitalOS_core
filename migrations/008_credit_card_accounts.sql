CREATE TABLE IF NOT EXISTS credit_card_accounts (
  id BIGSERIAL PRIMARY KEY,
  account_id BIGINT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  card_name TEXT NOT NULL,
  issuer TEXT NOT NULL,
  credit_limit NUMERIC(38, 18) NOT NULL,
  statement_day INTEGER NOT NULL,
  due_day INTEGER NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(account_id),
  CHECK (statement_day BETWEEN 1 AND 28),
  CHECK (due_day BETWEEN 1 AND 28)
);
