-- Normalize CASH assets to use currency symbols and merge duplicates.
WITH cash_assets AS (
  SELECT id, quote_currency
  FROM assets
  WHERE asset_class = 'CASH' AND UPPER(symbol) = 'CASH'
),
target_assets AS (
  SELECT id, quote_currency
  FROM assets
  WHERE asset_class = 'CASH' AND symbol = quote_currency
)
UPDATE positions p
SET asset_id = t.id
FROM cash_assets c
JOIN target_assets t ON t.quote_currency = c.quote_currency
WHERE p.asset_id = c.id;

DELETE FROM assets a
USING cash_assets c
JOIN target_assets t ON t.quote_currency = c.quote_currency
WHERE a.id = c.id;

UPDATE assets
SET symbol = quote_currency,
    name = COALESCE(name, quote_currency || ' Cash')
WHERE asset_class = 'CASH'
  AND (symbol IS NULL OR symbol = '' OR UPPER(symbol) = 'CASH');
