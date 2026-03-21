-- Migration 028: Add base_asset column to crypto_assets table for grouping derivatives
-- Purpose: Group crypto derivatives (ETH/wETH/stETH, BTC/wBTC/tBTC) into combined positions

BEGIN;

-- Add base_asset column
ALTER TABLE crypto_assets ADD COLUMN base_asset TEXT;

-- Update existing ETH derivatives to base_asset = 'ETH'
UPDATE crypto_assets
SET base_asset = 'ETH'
WHERE LOWER(symbol) IN ('eth', 'weth', 'steth', 'wsteth', 'eeth', 'weeth');

-- Update existing BTC derivatives to base_asset = 'BTC'
UPDATE crypto_assets
SET base_asset = 'BTC'
WHERE LOWER(symbol) IN ('btc', 'wbtc', 'fbtc', 'tbtc');

COMMIT;
