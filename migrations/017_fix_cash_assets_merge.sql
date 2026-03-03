-- Merge duplicate CASH assets (symbol = 'CASH') into currency-specific CASH assets.
WITH cash_assets AS (
  SELECT id, quote_currency
  FROM assets
  WHERE asset_class = 'CASH' AND UPPER(symbol) = 'CASH'
),
target_assets AS (
  SELECT id, quote_currency
  FROM assets
  WHERE asset_class = 'CASH' AND symbol = quote_currency
),
src AS (
  SELECT p.id, p.account_id, p.as_of, p.cost_basis_base, p.quantity, p.avg_cost, c.id AS cash_asset_id, t.id AS target_id
  FROM positions p
  JOIN cash_assets c ON c.id = p.asset_id
  JOIN target_assets t ON t.quote_currency = c.quote_currency
),
matched AS (
  SELECT s.*
  FROM src s
  JOIN positions p2 ON p2.account_id = s.account_id AND p2.as_of = s.as_of AND p2.asset_id = s.target_id
)
UPDATE positions p2
SET cost_basis_base = p2.cost_basis_base + m.cost_basis_base,
    quantity = COALESCE(p2.quantity, 0) + COALESCE(m.quantity, 0)
FROM matched m
WHERE p2.account_id = m.account_id AND p2.as_of = m.as_of AND p2.asset_id = m.target_id;

WITH cash_assets AS (
  SELECT id, quote_currency
  FROM assets
  WHERE asset_class = 'CASH' AND UPPER(symbol) = 'CASH'
),
target_assets AS (
  SELECT id, quote_currency
  FROM assets
  WHERE asset_class = 'CASH' AND symbol = quote_currency
),
src AS (
  SELECT p.id, p.account_id, p.as_of, c.id AS cash_asset_id, t.id AS target_id
  FROM positions p
  JOIN cash_assets c ON c.id = p.asset_id
  JOIN target_assets t ON t.quote_currency = c.quote_currency
),
matched AS (
  SELECT s.*
  FROM src s
  JOIN positions p2 ON p2.account_id = s.account_id AND p2.as_of = s.as_of AND p2.asset_id = s.target_id
)
DELETE FROM positions p
USING matched m
WHERE p.id = m.id;

WITH cash_assets AS (
  SELECT id, quote_currency
  FROM assets
  WHERE asset_class = 'CASH' AND UPPER(symbol) = 'CASH'
),
target_assets AS (
  SELECT id, quote_currency
  FROM assets
  WHERE asset_class = 'CASH' AND symbol = quote_currency
),
src AS (
  SELECT p.id, p.account_id, p.as_of, c.id AS cash_asset_id, t.id AS target_id
  FROM positions p
  JOIN cash_assets c ON c.id = p.asset_id
  JOIN target_assets t ON t.quote_currency = c.quote_currency
)
UPDATE positions p
SET asset_id = s.target_id
FROM src s
WHERE p.id = s.id
  AND NOT EXISTS (
    SELECT 1 FROM positions p2
    WHERE p2.account_id = s.account_id AND p2.as_of = s.as_of AND p2.asset_id = s.target_id
  );

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
DELETE FROM assets a
USING cash_assets c, target_assets t
WHERE a.id = c.id AND t.quote_currency = c.quote_currency;

UPDATE assets
SET symbol = quote_currency,
    name = COALESCE(name, quote_currency || ' Cash')
WHERE asset_class = 'CASH'
  AND (symbol IS NULL OR symbol = '' OR UPPER(symbol) = 'CASH');
