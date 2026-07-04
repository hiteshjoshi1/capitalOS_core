INSERT INTO parser_registry (format_signature, parser_key, version)
VALUES (
  '2c6766db5419e1fa6f96e4991f6f0bcd96b873f50c93a72ecfa367c47b81bd2a',
  'dbs_credit_card_csv_v1',
  1
)
ON CONFLICT (format_signature) DO NOTHING;

WITH demo_user AS (
  SELECT id AS user_id
  FROM users
  WHERE LOWER(username) = 'demo'
  LIMIT 1
),
dbs_platform AS (
  SELECT id AS platform_id
  FROM platforms
  WHERE code = 'DBS'
  LIMIT 1
)
INSERT INTO accounts (name, platform, user_id, account_type, currency, country, platform_id)
SELECT
  'DBS Credit Card',
  'DBS',
  demo_user.user_id,
  'CREDIT_CARD',
  'SGD',
  'SG',
  dbs_platform.platform_id
FROM demo_user
CROSS JOIN dbs_platform
WHERE NOT EXISTS (
  SELECT 1
  FROM accounts
  WHERE name = 'DBS Credit Card'
    AND platform = 'DBS'
    AND account_type = 'CREDIT_CARD'
    AND currency = 'SGD'
    AND user_id = demo_user.user_id
);

INSERT INTO credit_card_accounts (account_id, card_name, issuer, credit_limit, statement_day, due_day)
SELECT
  accounts.id,
  'DBS/POSB MasterCard Platinum (2403)',
  'DBS',
  60000,
  14,
  25
FROM accounts
JOIN users ON users.id = accounts.user_id
WHERE LOWER(users.username) = 'demo'
  AND accounts.name = 'DBS Credit Card'
  AND accounts.platform = 'DBS'
  AND accounts.account_type = 'CREDIT_CARD'
  AND accounts.currency = 'SGD'
ON CONFLICT (account_id) DO NOTHING;
