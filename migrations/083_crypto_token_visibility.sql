-- Spam/unknown wallet tokens (#342, D-87): a user's own choice for one token.
--
-- The crypto pages hide a contract token no snapshot of the user's wallets has ever priced
-- and that isn't on crypto_allowlist (app/crypto/token_visibility.py). A row here overrides
-- that for one token of one user: 'shown' ("Not spam") or 'hidden' ("Hide"). No row: automatic.
-- Identity is chain + contract address (lower-cased, as #331's token_key), never the symbol.
-- Valuation doesn't read this table; it only decides what the lists show.
CREATE TABLE IF NOT EXISTS crypto_token_visibility (
  user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  chain TEXT NOT NULL,
  contract_or_mint TEXT NOT NULL,
  visibility TEXT NOT NULL CHECK (visibility IN ('shown', 'hidden')),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, chain, contract_or_mint)
);
