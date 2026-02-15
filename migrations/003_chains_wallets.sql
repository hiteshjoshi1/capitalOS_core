CREATE TABLE IF NOT EXISTS chains (
  id         BIGSERIAL PRIMARY KEY,
  code       TEXT NOT NULL UNIQUE,  -- ETH, SOL
  name       TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Wallet metadata for accounts that represent wallets.
CREATE TABLE IF NOT EXISTS wallet_accounts (
  account_id BIGINT PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
  chain_id   BIGINT NOT NULL REFERENCES chains(id),
  address    TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(chain_id, address)
);
