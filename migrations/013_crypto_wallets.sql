CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS crypto_wallets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id BIGINT,
  chain_type TEXT NOT NULL, -- evm | solana
  chain TEXT NOT NULL, -- ethereum | base | arbitrum | optimism | mantle | scroll | solana
  address TEXT NOT NULL,
  label TEXT,
  status TEXT NOT NULL DEFAULT 'pending_verification',
  refresh_in_progress BOOLEAN NOT NULL DEFAULT FALSE,
  refresh_started_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  verified_at TIMESTAMPTZ,
  UNIQUE(chain_type, chain, address)
);

CREATE TABLE IF NOT EXISTS crypto_wallet_verifications (
  id BIGSERIAL PRIMARY KEY,
  wallet_id UUID NOT NULL REFERENCES crypto_wallets(id) ON DELETE CASCADE,
  nonce TEXT NOT NULL,
  message TEXT NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  used_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS crypto_assets (
  id BIGSERIAL PRIMARY KEY,
  chain_type TEXT NOT NULL,
  chain TEXT NOT NULL,
  asset_kind TEXT NOT NULL, -- native | erc20 | spl
  contract_or_mint TEXT,
  symbol TEXT,
  name TEXT,
  decimals INTEGER,
  UNIQUE(chain_type, chain, contract_or_mint)
);

CREATE TABLE IF NOT EXISTS crypto_wallet_snapshots (
  id BIGSERIAL PRIMARY KEY,
  wallet_id UUID NOT NULL REFERENCES crypto_wallets(id) ON DELETE CASCADE,
  as_of_date DATE NOT NULL,
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  total_usd NUMERIC,
  source_versions JSONB,
  UNIQUE(wallet_id, as_of_date)
);

CREATE TABLE IF NOT EXISTS crypto_wallet_snapshot_items (
  id BIGSERIAL PRIMARY KEY,
  snapshot_id BIGINT NOT NULL REFERENCES crypto_wallet_snapshots(id) ON DELETE CASCADE,
  asset_id BIGINT REFERENCES crypto_assets(id),
  chain_type TEXT NOT NULL,
  chain TEXT NOT NULL,
  asset_kind TEXT NOT NULL,
  contract_or_mint TEXT,
  symbol TEXT,
  name TEXT,
  decimals INTEGER,
  raw_amount TEXT,
  normalized_amount NUMERIC,
  price_usd NUMERIC,
  value_usd NUMERIC,
  price_source TEXT
);

CREATE TABLE IF NOT EXISTS crypto_user_networth (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT,
  as_of_date DATE NOT NULL,
  total_usd NUMERIC,
  crypto_usd NUMERIC,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(user_id, as_of_date)
);
