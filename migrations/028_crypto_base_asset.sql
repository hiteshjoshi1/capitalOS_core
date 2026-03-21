-- Migration 028: Add base_asset column to crypto_assets table for grouping derivatives
-- Purpose: Group crypto derivatives (ETH/wETH/stETH, BTC/wBTC/tBTC) into combined positions

BEGIN;

-- Add base_asset column
ALTER TABLE crypto_assets ADD COLUMN IF NOT EXISTS base_asset TEXT;

-- Update existing ETH derivatives to base_asset = 'ETH'
UPDATE crypto_assets
SET base_asset = 'ETH'
WHERE LOWER(symbol) IN ('eth', 'weth', 'steth', 'wsteth', 'eeth', 'weeth');

-- Update existing BTC derivatives to base_asset = 'BTC'
UPDATE crypto_assets
SET base_asset = 'BTC'
WHERE LOWER(symbol) IN ('btc', 'wbtc', 'fbtc', 'tbtc');

-- Validation: Check for symbol+chain combinations with conflicting base_asset values
-- This catches cases where the same symbol on the same chain has different base_asset mappings
DO $$
DECLARE
  collision_count INTEGER;
BEGIN
  SELECT COUNT(*) INTO collision_count
  FROM (
    SELECT LOWER(symbol) AS symbol_key, chain, COUNT(DISTINCT base_asset) AS base_asset_count
    FROM crypto_assets
    WHERE base_asset IS NOT NULL
    GROUP BY LOWER(symbol), chain
    HAVING COUNT(DISTINCT base_asset) > 1
  ) collisions;
  
  IF collision_count > 0 THEN
    RAISE WARNING 'Found % symbol+chain combinations with conflicting base_asset values. Review crypto_assets table.', collision_count;
  END IF;
END $$;

COMMIT;
