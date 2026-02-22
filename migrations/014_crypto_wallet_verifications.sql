ALTER TABLE crypto_wallet_verifications
  ADD COLUMN IF NOT EXISTS chain_type TEXT,
  ADD COLUMN IF NOT EXISTS chain TEXT,
  ADD COLUMN IF NOT EXISTS address TEXT;

ALTER TABLE crypto_wallet_verifications
  ALTER COLUMN wallet_id DROP NOT NULL;

ALTER TABLE crypto_wallet_verifications
  DROP CONSTRAINT IF EXISTS crypto_wallet_verifications_wallet_id_fkey;

ALTER TABLE crypto_wallet_verifications
  ADD CONSTRAINT crypto_wallet_verifications_wallet_id_fkey
  FOREIGN KEY (wallet_id) REFERENCES crypto_wallets(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_crypto_wallet_verifications_lookup
  ON crypto_wallet_verifications (chain_type, chain, address, used_at);
