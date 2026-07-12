-- Migration 064: Credit Card Merchant Category Rules
--
-- 1. Adds taxonomy entries for Travel and Utilities (new top-level categories).
-- 2. Seeds merchant-pattern rules so /categories/backfill can classify common
--    credit card purchases that still carry the "CreditCard::Purchase" placeholder.
-- 3. Bridges the human-readable raw categories emitted by the updated parsers
--    (e.g. "Groceries", "Dining") to the canonical taxonomy via source_category
--    pattern rules so backfill also resolves parser-assigned categories.
--
-- All INSERTs use ON CONFLICT / WHERE NOT EXISTS guards so the migration is safe
-- to run multiple times.

-- ──────────────────────────────────────────────────────────────────────────────
-- Part 1: New top-level taxonomy categories
-- ──────────────────────────────────────────────────────────────────────────────

INSERT INTO category_taxonomy (code, name, parent_id, display_order)
VALUES
  ('travel',     'Travel',    NULL, 45),
  ('utilities',  'Utilities', NULL, 55)
ON CONFLICT (code) DO NOTHING;

-- Sub-categories for travel
WITH parent AS (SELECT id FROM category_taxonomy WHERE code = 'travel')
INSERT INTO category_taxonomy (code, name, parent_id, display_order)
SELECT seed.code, seed.name, parent.id, seed.ord
FROM (VALUES
  ('travel_flights', 'Flights',          46),
  ('travel_hotel',   'Hotels',           47),
  ('travel_booking', 'Travel Bookings',  48)
) AS seed(code, name, ord)
CROSS JOIN parent
WHERE NOT EXISTS (
  SELECT 1 FROM category_taxonomy existing WHERE existing.code = seed.code
);

-- Sub-categories for utilities
WITH parent AS (SELECT id FROM category_taxonomy WHERE code = 'utilities')
INSERT INTO category_taxonomy (code, name, parent_id, display_order)
SELECT seed.code, seed.name, parent.id, seed.ord
FROM (VALUES
  ('utilities_telecom', 'Telecom',       56),
  ('utilities_power',   'Power & Water', 57)
) AS seed(code, name, ord)
CROSS JOIN parent
WHERE NOT EXISTS (
  SELECT 1 FROM category_taxonomy existing WHERE existing.code = seed.code
);

-- Pharmacy sub-category under health (if not already present)
WITH parent AS (SELECT id FROM category_taxonomy WHERE code = 'health')
INSERT INTO category_taxonomy (code, name, parent_id, display_order)
SELECT 'health_pharmacy', 'Pharmacy', parent.id, 62
FROM parent
WHERE NOT EXISTS (
  SELECT 1 FROM category_taxonomy existing WHERE existing.code = 'health_pharmacy'
);

-- ──────────────────────────────────────────────────────────────────────────────
-- Part 2: Merchant-pattern rules for existing CreditCard::Purchase transactions
--
-- These rules let /categories/backfill classify transactions that were imported
-- before the parser-level categorization was added (raw category still
-- "CreditCard::Purchase").  Each rule uses merchant_pattern + optional
-- source_category_pattern to narrow matches.
-- ──────────────────────────────────────────────────────────────────────────────

INSERT INTO category_rules (
  name, priority,
  merchant_pattern, source_category_pattern,
  target_category_id, active
)
SELECT
  seed.name,
  seed.priority,
  seed.merchant_pattern,
  seed.source_category_pattern,
  ct.id,
  TRUE
FROM (VALUES
  -- ── Groceries ──────────────────────────────────────────────────────────────
  ('CC Merchant: Sheng Siong Groceries',    200, '%SHENG SIONG%',   'CreditCard::Purchase', 'food_dining_groceries'),
  ('CC Merchant: NTUC FairPrice Groceries', 201, '%FAIRPRICE%',     'CreditCard::Purchase', 'food_dining_groceries'),
  ('CC Merchant: NTUC Groceries',           202, '%NTUC%',          'CreditCard::Purchase', 'food_dining_groceries'),
  ('CC Merchant: Cold Storage Groceries',   203, '%COLD STORAGE%',  'CreditCard::Purchase', 'food_dining_groceries'),
  ('CC Merchant: Giant Groceries',          204, '%GIANT%',         'CreditCard::Purchase', 'food_dining_groceries'),
  ('CC Merchant: RedMart Groceries',        205, '%REDMART%',       'CreditCard::Purchase', 'food_dining_groceries'),
  ('CC Merchant: Don Don Donki Groceries',  206, '%DON DON DONKI%', 'CreditCard::Purchase', 'food_dining_groceries'),
  -- ── Food delivery (before generic GRAB) ────────────────────────────────────
  ('CC Merchant: Grab Food Delivery',       210, '%GRAB FOOD%',     'CreditCard::Purchase', 'food_dining_restaurants'),
  ('CC Merchant: GrabFood Delivery',        211, '%GRABFOOD%',      'CreditCard::Purchase', 'food_dining_restaurants'),
  ('CC Merchant: Foodpanda Delivery',       212, '%FOODPANDA%',     'CreditCard::Purchase', 'food_dining_restaurants'),
  ('CC Merchant: Deliveroo Delivery',       213, '%DELIVEROO%',     'CreditCard::Purchase', 'food_dining_restaurants'),
  ('CC Merchant: UberEats Delivery',        214, '%UBER EATS%',     'CreditCard::Purchase', 'food_dining_restaurants'),
  -- ── Dining ─────────────────────────────────────────────────────────────────
  ('CC Merchant: Kopitiam Dining',          220, '%KOPITIAM%',      'CreditCard::Purchase', 'food_dining_restaurants'),
  ('CC Merchant: Starbucks Dining',         221, '%STARBUCKS%',     'CreditCard::Purchase', 'food_dining_restaurants'),
  ('CC Merchant: McDonald Dining',          222, '%MCDONALD%',      'CreditCard::Purchase', 'food_dining_restaurants'),
  ('CC Merchant: KFC Dining',               223, '%KFC%',           'CreditCard::Purchase', 'food_dining_restaurants'),
  ('CC Merchant: Subway Dining',            224, '%SUBWAY%',        'CreditCard::Purchase', 'food_dining_restaurants'),
  ('CC Merchant: Coffee Bean Dining',       225, '%COFFEE BEAN%',   'CreditCard::Purchase', 'food_dining_restaurants'),
  ('CC Merchant: Toast Box Dining',         226, '%TOAST BOX%',     'CreditCard::Purchase', 'food_dining_restaurants'),
  ('CC Merchant: Pizza Hut Dining',         227, '%PIZZA HUT%',     'CreditCard::Purchase', 'food_dining_restaurants'),
  ('CC Merchant: Old Chang Kee Dining',     228, '%OLD CHANG KEE%', 'CreditCard::Purchase', 'food_dining_restaurants'),
  -- ── Subscriptions ──────────────────────────────────────────────────────────
  ('CC Merchant: Netflix Subscription',     230, '%NETFLIX%',       'CreditCard::Purchase', 'entertainment_subscriptions'),
  ('CC Merchant: Spotify Subscription',     231, '%SPOTIFY%',       'CreditCard::Purchase', 'entertainment_subscriptions'),
  ('CC Merchant: Adobe Subscription',       232, '%ADOBE%',         'CreditCard::Purchase', 'entertainment_subscriptions'),
  ('CC Merchant: Dropbox Subscription',     233, '%DROPBOX%',       'CreditCard::Purchase', 'entertainment_subscriptions'),
  ('CC Merchant: Disney+ Subscription',     234, '%DISNEY%',        'CreditCard::Purchase', 'entertainment_subscriptions'),
  ('CC Merchant: OpenAI Subscription',      235, '%OPENAI%',        'CreditCard::Purchase', 'entertainment_subscriptions'),
  ('CC Merchant: ChatGPT Subscription',     236, '%CHATGPT%',       'CreditCard::Purchase', 'entertainment_subscriptions'),
  ('CC Merchant: GitHub Subscription',      237, '%GITHUB%',        'CreditCard::Purchase', 'entertainment_subscriptions'),
  ('CC Merchant: Zoom Subscription',        238, '%ZOOM%',          'CreditCard::Purchase', 'entertainment_subscriptions'),
  ('CC Merchant: Google Play Sub',          239, '%GOOGLE PLAY%',   'CreditCard::Purchase', 'entertainment_subscriptions'),
  ('CC Merchant: Apple Bill Subscription',  240, '%APPLE.COM/BILL%','CreditCard::Purchase', 'entertainment_subscriptions'),
  ('CC Merchant: Microsoft Sub',            241, '%MICROSOFT 36%',  'CreditCard::Purchase', 'entertainment_subscriptions'),
  ('CC Merchant: Amazon Prime Sub',         242, '%AMAZON PRIME%',  'CreditCard::Purchase', 'entertainment_subscriptions'),
  -- ── Transport (after food delivery rules so GRAB FOOD → Dining wins) ───────
  ('CC Merchant: Grab Transport',           250, '%GRAB%',          'CreditCard::Purchase', 'transportation_rideshare'),
  ('CC Merchant: Gojek Transport',          251, '%GOJEK%',         'CreditCard::Purchase', 'transportation_rideshare'),
  ('CC Merchant: ComfortDelGro Transport',  252, '%COMFORTDELGRO%', 'CreditCard::Purchase', 'transportation_rideshare'),
  ('CC Merchant: EZ Link Transit',          253, '%EZ LINK%',       'CreditCard::Purchase', 'transportation_public'),
  ('CC Merchant: SMRT Transit',             254, '%SMRT%',          'CreditCard::Purchase', 'transportation_public'),
  -- ── Travel ─────────────────────────────────────────────────────────────────
  ('CC Merchant: Singapore Airlines Travel',260, '%SINGAPORE AIRLINES%','CreditCard::Purchase', 'travel_flights'),
  ('CC Merchant: Scoot Travel',             261, '%SCOOT%',             'CreditCard::Purchase', 'travel_flights'),
  ('CC Merchant: Jetstar Travel',           262, '%JETSTAR%',           'CreditCard::Purchase', 'travel_flights'),
  ('CC Merchant: AirAsia Travel',           263, '%AIRASIA%',           'CreditCard::Purchase', 'travel_flights'),
  ('CC Merchant: Booking.com Travel',       264, '%BOOKING.COM%',       'CreditCard::Purchase', 'travel_hotel'),
  ('CC Merchant: Agoda Travel',             265, '%AGODA%',             'CreditCard::Purchase', 'travel_hotel'),
  ('CC Merchant: Airbnb Travel',            266, '%AIRBNB%',            'CreditCard::Purchase', 'travel_hotel'),
  ('CC Merchant: Expedia Travel',           267, '%EXPEDIA%',           'CreditCard::Purchase', 'travel_booking'),
  ('CC Merchant: Klook Travel',             268, '%KLOOK%',             'CreditCard::Purchase', 'travel_booking'),
  -- ── Shopping ───────────────────────────────────────────────────────────────
  ('CC Merchant: Lazada Shopping',          270, '%LAZADA%',        'CreditCard::Purchase', 'shopping_general'),
  ('CC Merchant: Shopee Shopping',          271, '%SHOPEE%',        'CreditCard::Purchase', 'shopping_general'),
  ('CC Merchant: Amazon Shopping',          272, '%AMAZON%',        'CreditCard::Purchase', 'shopping_general'),
  ('CC Merchant: Zalora Shopping',          273, '%ZALORA%',        'CreditCard::Purchase', 'shopping_general'),
  ('CC Merchant: Uniqlo Shopping',          274, '%UNIQLO%',        'CreditCard::Purchase', 'shopping_general'),
  ('CC Merchant: IKEA Shopping',            275, '%IKEA%',          'CreditCard::Purchase', 'shopping_general'),
  -- ── Utilities ──────────────────────────────────────────────────────────────
  ('CC Merchant: Singtel Utilities',        280, '%SINGTEL%',       'CreditCard::Purchase', 'utilities_telecom'),
  ('CC Merchant: StarHub Utilities',        281, '%STARHUB%',       'CreditCard::Purchase', 'utilities_telecom'),
  ('CC Merchant: SP Services Utilities',    282, '%SP SERVICES%',   'CreditCard::Purchase', 'utilities_power'),
  -- ── Medical ────────────────────────────────────────────────────────────────
  ('CC Merchant: Watsons Pharmacy',         290, '%WATSONS%',       'CreditCard::Purchase', 'health_pharmacy'),
  ('CC Merchant: Guardian Pharmacy',        291, '%GUARDIAN%',      'CreditCard::Purchase', 'health_pharmacy'),
  ('CC Merchant: Raffles Medical',          292, '%RAFFLES MEDICAL%','CreditCard::Purchase', 'health_medical'),
  ('CC Merchant: Polyclinic',               293, '%POLYCLINIC%',    'CreditCard::Purchase', 'health_medical')
) AS seed(name, priority, merchant_pattern, source_category_pattern, target_code)
JOIN category_taxonomy ct ON ct.code = seed.target_code
WHERE NOT EXISTS (
  SELECT 1 FROM category_rules existing WHERE existing.name = seed.name
);

-- ──────────────────────────────────────────────────────────────────────────────
-- Part 3: Source-category-pattern rules bridging parser-emitted friendly names
--         to taxonomy so backfill also works for newly imported transactions.
-- ──────────────────────────────────────────────────────────────────────────────

INSERT INTO category_rules (
  name, priority,
  source_category_pattern,
  target_category_id, active
)
SELECT
  seed.name,
  seed.priority,
  seed.source_category_pattern,
  ct.id,
  TRUE
FROM (VALUES
  ('Bridge CC Groceries to taxonomy',      300, 'Groceries',    'food_dining_groceries'),
  ('Bridge CC Dining to taxonomy',         301, 'Dining',       'food_dining_restaurants'),
  ('Bridge CC Transport to taxonomy',      302, 'Transport',    'transportation_rideshare'),
  ('Bridge CC Subscriptions to taxonomy',  303, 'Subscriptions','entertainment_subscriptions'),
  ('Bridge CC Shopping to taxonomy',       304, 'Shopping',     'shopping_general'),
  ('Bridge CC Travel to taxonomy',         305, 'Travel',       'travel'),
  ('Bridge CC Utilities to taxonomy',      306, 'Utilities',    'utilities'),
  ('Bridge CC Medical to taxonomy',        307, 'Medical',      'health_medical')
) AS seed(name, priority, source_category_pattern, target_code)
JOIN category_taxonomy ct ON ct.code = seed.target_code
WHERE NOT EXISTS (
  SELECT 1 FROM category_rules existing WHERE existing.name = seed.name
);
