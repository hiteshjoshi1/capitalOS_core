ALTER TABLE credit_card_accounts
  ADD COLUMN IF NOT EXISTS available_limit NUMERIC(38, 18);

ALTER TABLE credit_card_accounts
  ADD COLUMN IF NOT EXISTS available_limit_as_of TIMESTAMPTZ;
