DO $$ BEGIN
  CREATE TYPE platform_type AS ENUM ('BANK','BROKER','EXCHANGE','CARD_ISSUER','WALLET_PROVIDER');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS platforms (
  id            BIGSERIAL PRIMARY KEY,
  code          TEXT NOT NULL UNIQUE, -- DBS, OCBC, UOB, IBKR, COINBASE, CITI, SHAREKHAN
  name          TEXT NOT NULL,
  platform_type platform_type NOT NULL,
  country       TEXT NOT NULL,        -- SG, IN, US, HK, etc
  website       TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Optional: tighten accounts.platform from TEXT -> FK
-- Keep current column for now and add a new FK column.
ALTER TABLE accounts
  ADD COLUMN IF NOT EXISTS platform_id BIGINT REFERENCES platforms(id);
