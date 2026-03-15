CREATE TABLE IF NOT EXISTS category_taxonomy (
  id BIGSERIAL PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  parent_id BIGINT REFERENCES category_taxonomy(id) ON DELETE SET NULL,
  display_order INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS category_rules (
  id BIGSERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  priority INTEGER NOT NULL DEFAULT 100,
  merchant_pattern TEXT,
  description_pattern TEXT,
  source_category_pattern TEXT,
  txn_type txn_type,
  min_amount NUMERIC(38, 18),
  max_amount NUMERIC(38, 18),
  target_category_id BIGINT NOT NULL REFERENCES category_taxonomy(id),
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (min_amount IS NULL OR max_amount IS NULL OR min_amount <= max_amount)
);

CREATE TABLE IF NOT EXISTS category_overrides (
  id BIGSERIAL PRIMARY KEY,
  transaction_id BIGINT NOT NULL UNIQUE REFERENCES transactions(id) ON DELETE CASCADE,
  category_id BIGINT NOT NULL REFERENCES category_taxonomy(id),
  source TEXT NOT NULL CHECK (source IN ('rule', 'manual')),
  rule_id BIGINT REFERENCES category_rules(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_category_taxonomy_parent_id
  ON category_taxonomy(parent_id);

CREATE INDEX IF NOT EXISTS idx_category_rules_active_priority
  ON category_rules(active, priority, id);

CREATE INDEX IF NOT EXISTS idx_category_overrides_transaction_id
  ON category_overrides(transaction_id);

CREATE INDEX IF NOT EXISTS idx_category_overrides_rule_id
  ON category_overrides(rule_id);

INSERT INTO category_taxonomy (code, name, parent_id, display_order)
VALUES
  ('income', 'Income', NULL, 10),
  ('housing', 'Housing', NULL, 20),
  ('food_dining', 'Food & Dining', NULL, 30),
  ('transportation', 'Transportation', NULL, 40),
  ('shopping', 'Shopping', NULL, 50),
  ('health', 'Health', NULL, 60),
  ('entertainment', 'Entertainment', NULL, 70),
  ('financial', 'Financial', NULL, 80),
  ('taxes', 'Taxes', NULL, 90),
  ('transfer', 'Transfer', NULL, 100),
  ('uncategorized', 'Uncategorized', NULL, 110)
ON CONFLICT (code) DO NOTHING;

WITH parent_rows AS (
  SELECT id, code
  FROM category_taxonomy
)
INSERT INTO category_taxonomy (code, name, parent_id, display_order)
VALUES
  ('income_salary', 'Salary', (SELECT id FROM parent_rows WHERE code = 'income'), 11),
  ('income_dividends', 'Dividends', (SELECT id FROM parent_rows WHERE code = 'income'), 12),
  ('income_interest', 'Interest', (SELECT id FROM parent_rows WHERE code = 'income'), 13),
  ('housing_rent', 'Rent', (SELECT id FROM parent_rows WHERE code = 'housing'), 21),
  ('food_dining_groceries', 'Groceries', (SELECT id FROM parent_rows WHERE code = 'food_dining'), 31),
  ('food_dining_restaurants', 'Dining Out', (SELECT id FROM parent_rows WHERE code = 'food_dining'), 32),
  ('transportation_public', 'Public Transit', (SELECT id FROM parent_rows WHERE code = 'transportation'), 41),
  ('transportation_rideshare', 'Rideshare', (SELECT id FROM parent_rows WHERE code = 'transportation'), 42),
  ('shopping_general', 'General Shopping', (SELECT id FROM parent_rows WHERE code = 'shopping'), 51),
  ('health_medical', 'Medical', (SELECT id FROM parent_rows WHERE code = 'health'), 61),
  ('entertainment_subscriptions', 'Subscriptions', (SELECT id FROM parent_rows WHERE code = 'entertainment'), 71),
  ('financial_investment_fees', 'Investment Fees', (SELECT id FROM parent_rows WHERE code = 'financial'), 81),
  ('taxes_withholding', 'Withholding Tax', (SELECT id FROM parent_rows WHERE code = 'taxes'), 91),
  ('transfer_internal', 'Internal Transfer', (SELECT id FROM parent_rows WHERE code = 'transfer'), 101),
  ('transfer_credit_card_payment', 'Credit Card Payment', (SELECT id FROM parent_rows WHERE code = 'transfer'), 102),
  ('transfer_brokerage', 'Brokerage Transfer', (SELECT id FROM parent_rows WHERE code = 'transfer'), 103)
ON CONFLICT (code) DO NOTHING;

INSERT INTO category_rules (
  name,
  priority,
  source_category_pattern,
  target_category_id,
  active
)
SELECT
  seed.name,
  seed.priority,
  seed.source_category_pattern,
  ct.id,
  TRUE
FROM (
  VALUES
    ('Bridge Brokerage Dividends', 10, 'Brokerage::Dividend', 'income_dividends'),
    ('Bridge Brokerage Interest', 20, 'Brokerage::Interest', 'income_interest'),
    ('Bridge Brokerage Fees', 30, 'Brokerage::Fee', 'financial_investment_fees'),
    ('Bridge Brokerage Tax', 40, 'Brokerage::Tax', 'taxes_withholding'),
    ('Bridge Bank Transfer', 50, 'Bank::Transfer', 'transfer_internal'),
    ('Bridge Credit Card Payment', 60, 'CreditCard::Payment', 'transfer_credit_card_payment'),
    ('Bridge Brokerage Transfer', 70, 'Brokerage::Transfer', 'transfer_brokerage')
) AS seed(name, priority, source_category_pattern, target_code)
JOIN category_taxonomy ct ON ct.code = seed.target_code
WHERE NOT EXISTS (
  SELECT 1
  FROM category_rules existing
  WHERE existing.name = seed.name
);
