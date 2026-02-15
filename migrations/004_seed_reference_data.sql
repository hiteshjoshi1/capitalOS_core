-- Platforms: Singapore
INSERT INTO platforms (code, name, platform_type, country, website) VALUES
  ('DBS', 'DBS', 'BANK', 'SG', 'https://www.dbs.com.sg'),
  ('OCBC', 'OCBC', 'BANK', 'SG', 'https://www.ocbc.com'),
  ('UOB', 'UOB', 'BANK', 'SG', 'https://www.uob.com.sg'),
  ('DBS_VICKERS', 'DBS Vickers', 'BROKER', 'SG', 'https://www.dbsvickers.com'),
  ('IBKR', 'Interactive Brokers', 'BROKER', 'US', 'https://www.interactivebrokers.com'),
  ('COINBASE', 'Coinbase', 'EXCHANGE', 'US', 'https://www.coinbase.com'),
  ('CITI', 'Citi', 'CARD_ISSUER', 'US', 'https://www.citi.com'),
  ('UOB_CARDS', 'UOB Cards', 'CARD_ISSUER', 'SG', 'https://www.uob.com.sg'),
  ('DBS_CARDS', 'DBS Cards', 'CARD_ISSUER', 'SG', 'https://www.dbs.com.sg');

-- Platforms: India
INSERT INTO platforms (code, name, platform_type, country, website) VALUES
  ('SBI', 'State Bank of India', 'BANK', 'IN', 'https://sbi.co.in'),
  ('AXIS', 'Axis Bank', 'BANK', 'IN', 'https://www.axisbank.com'),
  ('SHAREKHAN', 'Sharekhan', 'BROKER', 'IN', 'https://www.sharekhan.com')
ON CONFLICT (code) DO NOTHING;

-- Wallet provider (generic)
INSERT INTO platforms (code, name, platform_type, country, website) VALUES
  ('WALLET', 'Self-custody Wallet', 'WALLET_PROVIDER', 'GLOBAL', NULL)
ON CONFLICT (code) DO NOTHING;

-- Chains
INSERT INTO chains (code, name) VALUES
  ('ETH', 'Ethereum'),
  ('SOL', 'Solana')
ON CONFLICT (code) DO NOTHING;
