CREATE TABLE IF NOT EXISTS crypto_allowlist (
  id BIGSERIAL PRIMARY KEY,
  chain TEXT NOT NULL,
  contract_address TEXT NOT NULL,
  symbol TEXT,
  name TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(chain, contract_address)
);
