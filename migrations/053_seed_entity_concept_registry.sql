-- Migration 053: Seed entity and concept registry for RAG extraction (Issue 170)
-- Idempotent: all inserts use ON CONFLICT DO NOTHING.
-- Registry version date: 2026-05-27

-- ─────────────────────────────────────────────────────────────────────────────
-- ENTITIES: Companies (entity_type = 'company')
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO rag_entities (id, entity_type, canonical_name) VALUES
  ('amazon',            'company', 'Amazon'),
  ('berkshire_hathaway','company', 'Berkshire Hathaway'),
  ('apple',             'company', 'Apple'),
  ('alphabet',          'company', 'Alphabet / Google'),
  ('microsoft',         'company', 'Microsoft'),
  ('costco',            'company', 'Costco'),
  ('coca_cola',         'company', 'Coca-Cola'),
  ('wells_fargo',       'company', 'Wells Fargo'),
  ('byd',               'company', 'BYD'),
  ('walmart',           'company', 'Walmart'),
  ('meta',              'company', 'Meta / Facebook'),
  ('netflix',           'company', 'Netflix'),
  ('tesla',             'company', 'Tesla'),
  ('samsung',           'company', 'Samsung'),
  ('alibaba',           'company', 'Alibaba'),
  ('toyota',            'company', 'Toyota'),
  ('visa',              'company', 'Visa'),
  ('jpmorgan',          'company', 'JPMorgan Chase'),
  ('american_express',  'company', 'American Express'),
  ('moodys',            'company', 'Moody''s'),
  ('sees_candies',      'company', 'See''s Candies'),
  ('geico',             'company', 'GEICO'),
  ('wesco',             'company', 'Wesco Financial'),
  ('djco',              'company', 'Daily Journal Corporation'),
  ('ford_motor',        'company', 'Ford Motor Company')
ON CONFLICT DO NOTHING;

-- ─────────────────────────────────────────────────────────────────────────────
-- ENTITIES: People — non-author persons (entity_type = 'person')
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO rag_entities (id, entity_type, canonical_name) VALUES
  ('jeff_bezos',          'person', 'Jeff Bezos'),
  ('elon_musk',           'person', 'Elon Musk'),
  ('bill_gates',          'person', 'Bill Gates'),
  ('henry_ford',          'person', 'Henry Ford'),
  ('sam_walton',          'person', 'Sam Walton'),
  ('john_d_rockefeller',  'person', 'John D. Rockefeller'),
  ('adam_smith',          'person', 'Adam Smith'),
  ('ben_franklin',        'person', 'Benjamin Franklin')
ON CONFLICT DO NOTHING;

-- ─────────────────────────────────────────────────────────────────────────────
-- ENTITY ALIASES: Companies
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO rag_entity_aliases (entity_id, alias, alias_type, is_active) VALUES
  -- Amazon
  ('amazon', 'amazon',     'name',    TRUE),
  ('amazon', 'amazon.com', 'name',    TRUE),
  ('amazon', 'amzn',       'ticker',  TRUE),

  -- Berkshire Hathaway
  ('berkshire_hathaway', 'berkshire hathaway', 'name',       TRUE),
  ('berkshire_hathaway', 'berkshire',          'short_name', TRUE),
  ('berkshire_hathaway', 'brk',                'ticker',     TRUE),
  ('berkshire_hathaway', 'brk.a',              'ticker',     TRUE),
  ('berkshire_hathaway', 'brk.b',              'ticker',     TRUE),
  ('berkshire_hathaway', 'brk-b',              'ticker',     TRUE),

  -- Apple
  ('apple', 'apple',     'name',   TRUE),
  ('apple', 'apple inc', 'name',   TRUE),
  ('apple', 'aapl',      'ticker', TRUE),

  -- Alphabet
  ('alphabet', 'alphabet', 'name',   TRUE),
  ('alphabet', 'google',   'name',   TRUE),
  ('alphabet', 'googl',    'ticker', TRUE),
  ('alphabet', 'goog',     'ticker', TRUE),

  -- Microsoft
  ('microsoft', 'microsoft', 'name',   TRUE),
  ('microsoft', 'msft',      'ticker', TRUE),

  -- Costco
  ('costco', 'costco',           'name',   TRUE),
  ('costco', 'costco wholesale', 'name',   TRUE),
  -- 'cost' is ambiguous with the generic word; inserted inactive below

  -- Coca-Cola
  ('coca_cola', 'coca-cola',  'name',   TRUE),
  ('coca_cola', 'coca cola',  'name',   TRUE),
  ('coca_cola', 'coke',       'name',   TRUE),
  -- Single-char ticker 'ko' excluded per short ticker policy (see below)

  -- Wells Fargo
  ('wells_fargo', 'wells fargo', 'name',   TRUE),
  ('wells_fargo', 'wfc',         'ticker', TRUE),

  -- BYD
  ('byd', 'byd',         'name', TRUE),
  ('byd', 'byd company', 'name', TRUE),

  -- Walmart
  ('walmart', 'walmart',  'name',   TRUE),
  ('walmart', 'wal-mart', 'name',   TRUE),
  ('walmart', 'wmt',      'ticker', TRUE),

  -- Meta / Facebook
  ('meta', 'facebook', 'name', TRUE),
  -- 'meta' is ambiguous with generic adjective; inserted inactive below

  -- Netflix
  ('netflix', 'netflix', 'name',   TRUE),
  ('netflix', 'nflx',    'ticker', TRUE),

  -- Tesla
  ('tesla', 'tesla', 'name',   TRUE),
  ('tesla', 'tsla',  'ticker', TRUE),

  -- Samsung
  ('samsung', 'samsung', 'name', TRUE),

  -- Alibaba
  ('alibaba', 'alibaba', 'name',   TRUE),
  ('alibaba', 'baba',    'ticker', TRUE),

  -- Toyota
  ('toyota', 'toyota', 'name', TRUE),

  -- Visa
  ('visa', 'visa', 'name', TRUE),
  -- Single-char ticker 'v' excluded per short ticker policy

  -- JPMorgan
  ('jpmorgan', 'jpmorgan',       'name',   TRUE),
  ('jpmorgan', 'jpmorgan chase', 'name',   TRUE),
  ('jpmorgan', 'jpm',            'ticker', TRUE),

  -- American Express
  ('american_express', 'american express', 'name',   TRUE),
  ('american_express', 'amex',             'name',   TRUE),

  -- Moody's
  ('moodys', 'moodys',   'name', TRUE),
  ('moodys', 'moody''s', 'name', TRUE),

  -- See's Candies
  ('sees_candies', 'see''s candies', 'name',       TRUE),
  ('sees_candies', 'sees candies',   'name',       TRUE),
  ('sees_candies', 'sees',           'short_name', TRUE),

  -- GEICO
  ('geico', 'geico', 'name', TRUE),

  -- Wesco Financial
  ('wesco', 'wesco',           'name', TRUE),
  ('wesco', 'wesco financial', 'name', TRUE),

  -- Daily Journal Corporation
  ('djco', 'daily journal', 'name',   TRUE),
  ('djco', 'djco',          'ticker', TRUE),

  -- Ford Motor (note: 'ford' is active on henry_ford; ford_motor uses 'ford motor' only)
  ('ford_motor', 'ford motor',         'name', TRUE),
  ('ford_motor', 'ford motor company', 'name', TRUE)

ON CONFLICT DO NOTHING;

-- ─────────────────────────────────────────────────────────────────────────────
-- ENTITY ALIASES: People
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO rag_entity_aliases (entity_id, alias, alias_type, is_active) VALUES
  ('jeff_bezos',         'jeff bezos',         'name', TRUE),
  ('jeff_bezos',         'bezos',              'name', TRUE),

  ('elon_musk',          'elon musk',          'name', TRUE),
  -- 'musk' active below after collision policy review
  ('elon_musk',          'musk',               'name', TRUE),

  ('bill_gates',         'bill gates',         'name', TRUE),
  -- 'gates' active below after collision policy review
  ('bill_gates',         'gates',              'name', TRUE),

  ('henry_ford',         'henry ford',         'name', TRUE),
  -- 'ford' active on henry_ford; ford_motor uses 'ford motor' only
  ('henry_ford',         'ford',               'name', TRUE),

  ('sam_walton',         'sam walton',         'name', TRUE),
  ('sam_walton',         'walton',             'name', TRUE),

  ('john_d_rockefeller', 'john d. rockefeller','name', TRUE),
  ('john_d_rockefeller', 'rockefeller',        'name', TRUE),

  ('adam_smith',         'adam smith',         'name', TRUE),

  ('ben_franklin',       'benjamin franklin',  'name', TRUE),
  ('ben_franklin',       'ben franklin',       'name', TRUE)
ON CONFLICT DO NOTHING;

-- ─────────────────────────────────────────────────────────────────────────────
-- AMBIGUOUS ALIASES: inserted as is_active=FALSE with explanatory comments.
-- These are excluded from extraction but remain visible and recoverable.
-- ─────────────────────────────────────────────────────────────────────────────

-- 'meta': Meta/Facebook vs generic adjective.
-- Active alias is 'facebook'. Use 'meta platforms' when corpus evidence confirms safe.
INSERT INTO rag_entity_aliases (entity_id, alias, alias_type, is_active)
VALUES ('meta', 'meta', 'name', FALSE)
ON CONFLICT DO NOTHING;

-- 'cost': Costco ticker vs generic word.
-- Active aliases are 'costco' and 'costco wholesale'. Activate when corpus confirms safe.
INSERT INTO rag_entity_aliases (entity_id, alias, alias_type, is_active)
VALUES ('costco', 'cost', 'ticker', FALSE)
ON CONFLICT DO NOTHING;

-- 'float': generic word vs insurance float concept.
-- Handled in the concept registry: insurance_float uses 'insurance float' as primary.
-- 'float' is inserted inactive in concepts to document the decision (see concept aliases).

-- 'ford': henry_ford (person) vs ford_motor (company). Active on henry_ford; ford_motor
-- uses explicit 'ford motor' alias only. No inactive insertion needed — person wins by design.

-- 'apple': company vs common noun. Active on apple entity; low false-positive risk
-- in investment prose. No inactive insertion needed.

-- 'gates': Bill Gates vs generic word. Active on bill_gates; low false-positive risk. No inactive needed.

-- 'musk': Elon Musk vs generic word. Active on elon_musk; low false-positive risk. No inactive needed.

-- ─────────────────────────────────────────────────────────────────────────────
-- SHORT TICKER POLICY: single and two-character tickers inserted as is_active=FALSE.
-- They can be activated in a follow-up migration once tighter boundary patterns are
-- validated against a sample corpus.
-- ─────────────────────────────────────────────────────────────────────────────

-- 'ko' (Coca-Cola, 2 chars)
INSERT INTO rag_entity_aliases (entity_id, alias, alias_type, is_active)
VALUES ('coca_cola', 'ko', 'ticker', FALSE)
ON CONFLICT DO NOTHING;

-- 'v' (Visa, 1 char)
INSERT INTO rag_entity_aliases (entity_id, alias, alias_type, is_active)
VALUES ('visa', 'v', 'ticker', FALSE)
ON CONFLICT DO NOTHING;

-- 'f' (Ford, 1 char)
INSERT INTO rag_entity_aliases (entity_id, alias, alias_type, is_active)
VALUES ('ford_motor', 'f', 'ticker', FALSE)
ON CONFLICT DO NOTHING;

-- ─────────────────────────────────────────────────────────────────────────────
-- CONCEPTS: Domain 'valuation'
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO rag_concepts (id, canonical_name, domain) VALUES
  ('intrinsic_value',   'Intrinsic Value',        'valuation'),
  ('margin_of_safety',  'Margin of Safety',       'valuation'),
  ('owner_earnings',    'Owner Earnings',         'valuation'),
  ('dcf',               'Discounted Cash Flow',   'valuation'),
  ('price_to_earnings', 'Price-to-Earnings',      'valuation'),
  ('book_value',        'Book Value',             'valuation')
ON CONFLICT DO NOTHING;

-- ─────────────────────────────────────────────────────────────────────────────
-- CONCEPTS: Domain 'investing'
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO rag_concepts (id, canonical_name, domain) VALUES
  ('moat',                    'Economic Moat',             'investing'),
  ('circle_of_competence',    'Circle of Competence',      'investing'),
  ('capital_allocation',      'Capital Allocation',        'investing'),
  ('reinvestment',            'Reinvestment',              'investing'),
  ('pricing_power',           'Pricing Power',             'investing'),
  ('competitive_advantage',   'Competitive Advantage',     'investing'),
  ('long_termism',            'Long-Termism',              'investing'),
  ('checklist',               'Investing Checklist',       'investing'),
  ('opportunity_cost',        'Opportunity Cost',          'investing'),
  ('position_sizing',         'Position Sizing',           'investing'),
  ('scale_economies_shared',  'Scale Economies Shared',    'investing'),
  ('customer_obsession',      'Customer Obsession',        'investing'),
  ('flywheel',                'Flywheel Effect',           'investing'),
  ('network_effects',         'Network Effects',           'investing'),
  ('switching_costs',         'Switching Costs',           'investing'),
  ('insurance_float',         'Insurance Float',           'investing'),
  ('share_buybacks',          'Share Buybacks',            'investing')
ON CONFLICT DO NOTHING;

-- ─────────────────────────────────────────────────────────────────────────────
-- CONCEPTS: Domain 'psychology'
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO rag_concepts (id, canonical_name, domain) VALUES
  ('mental_models',      'Mental Models',          'psychology'),
  ('inversion',          'Inversion',              'psychology'),
  ('incentives',         'Incentives',             'psychology'),
  ('social_proof',       'Social Proof',           'psychology'),
  ('loss_aversion',      'Loss Aversion',          'psychology'),
  ('authority_bias',     'Authority Bias',         'psychology'),
  ('availability_bias',  'Availability Bias',      'psychology'),
  ('lollapalooza',       'Lollapalooza Effect',    'psychology'),
  ('temperament',        'Investor Temperament',   'psychology'),
  ('mr_market',          'Mr. Market',             'psychology')
ON CONFLICT DO NOTHING;

-- ─────────────────────────────────────────────────────────────────────────────
-- CONCEPTS: Domain 'operations'
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO rag_concepts (id, canonical_name, domain) VALUES
  ('management_quality', 'Management Quality', 'operations'),
  ('corporate_culture',  'Corporate Culture',  'operations'),
  ('owner_operator',     'Owner-Operator',     'operations')
ON CONFLICT DO NOTHING;

-- ─────────────────────────────────────────────────────────────────────────────
-- CONCEPTS: Domain 'macro'
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO rag_concepts (id, canonical_name, domain) VALUES
  ('inflation',              'Inflation',              'macro'),
  ('interest_rates',         'Interest Rates',         'macro'),
  ('second_level_thinking',  'Second-Level Thinking',  'macro')
ON CONFLICT DO NOTHING;

-- ─────────────────────────────────────────────────────────────────────────────
-- CONCEPTS: Domain 'valuation' (additional — to satisfy >= 50 concept target)
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO rag_concepts (id, canonical_name, domain) VALUES
  ('free_cash_flow',         'Free Cash Flow',           'valuation'),
  ('enterprise_value',       'Enterprise Value',         'valuation'),
  ('return_on_equity',       'Return on Equity',         'valuation'),
  ('return_on_capital',      'Return on Invested Capital','valuation'),
  ('earnings_yield',         'Earnings Yield',           'valuation'),
  ('compound_interest',      'Compounding',              'valuation')
ON CONFLICT DO NOTHING;

-- ─────────────────────────────────────────────────────────────────────────────
-- CONCEPTS: Domain 'investing' (additional)
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO rag_concepts (id, canonical_name, domain) VALUES
  ('value_investing',        'Value Investing',          'investing'),
  ('contrarian',             'Contrarian Investing',     'investing'),
  ('patience',               'Patience',                 'investing'),
  ('risk_management',        'Risk Management',          'investing'),
  ('mean_reversion',         'Mean Reversion',           'investing')
ON CONFLICT DO NOTHING;

-- ─────────────────────────────────────────────────────────────────────────────
-- CONCEPT ALIASES: valuation
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO rag_concept_aliases (concept_id, alias, is_active) VALUES
  ('intrinsic_value',   'intrinsic value',    TRUE),
  ('intrinsic_value',   'intrinsic worth',    TRUE),

  ('margin_of_safety',  'margin of safety',   TRUE),

  ('owner_earnings',    'owner earnings',     TRUE),

  ('dcf',               'dcf',                TRUE),
  ('dcf',               'discounted cash flow', TRUE),

  ('price_to_earnings', 'p/e ratio',          TRUE),
  ('price_to_earnings', 'price-to-earnings',  TRUE),
  ('price_to_earnings', 'price to earnings',  TRUE),

  ('book_value',        'book value',         TRUE),
  ('book_value',        'price-to-book',      TRUE),
  ('book_value',        'p/b ratio',          TRUE)
ON CONFLICT DO NOTHING;

-- ─────────────────────────────────────────────────────────────────────────────
-- CONCEPT ALIASES: investing
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO rag_concept_aliases (concept_id, alias, is_active) VALUES
  ('moat',                   'moat',                          TRUE),
  ('moat',                   'economic moat',                 TRUE),
  ('moat',                   'durable competitive advantage', TRUE),

  ('circle_of_competence',   'circle of competence',          TRUE),

  ('capital_allocation',     'capital allocation',            TRUE),

  ('reinvestment',           'reinvestment',                  TRUE),
  ('reinvestment',           'reinvest',                      TRUE),
  ('reinvestment',           'reinvesting',                   TRUE),

  ('pricing_power',          'pricing power',                 TRUE),

  ('competitive_advantage',  'competitive advantage',         TRUE),
  ('competitive_advantage',  'sustainable advantage',         TRUE),

  ('long_termism',           'long-termism',                  TRUE),
  ('long_termism',           'long-term thinking',            TRUE),
  ('long_termism',           'long-term orientation',         TRUE),

  ('checklist',              'checklist',                     TRUE),

  ('opportunity_cost',       'opportunity cost',              TRUE),

  ('position_sizing',        'position sizing',               TRUE),
  ('position_sizing',        'portfolio concentration',       TRUE),

  ('scale_economies_shared', 'scale economies shared',        TRUE),
  ('scale_economies_shared', 'scale economies',               TRUE),

  ('customer_obsession',     'customer obsession',            TRUE),
  ('customer_obsession',     'customer focus',                TRUE),

  ('flywheel',               'flywheel',                      TRUE),
  ('flywheel',               'flywheel effect',               TRUE),
  ('flywheel',               'virtuous cycle',                TRUE),

  ('network_effects',        'network effects',               TRUE),
  ('network_effects',        'network effect',                TRUE),

  ('switching_costs',        'switching costs',               TRUE),
  ('switching_costs',        'switching cost',                TRUE),
  ('switching_costs',        'lock-in',                       TRUE),

  ('insurance_float',        'insurance float',               TRUE),
  -- 'float' alone is a generic word; inserted inactive below

  ('share_buybacks',         'share buybacks',                TRUE),
  ('share_buybacks',         'buyback',                       TRUE),
  ('share_buybacks',         'share repurchase',              TRUE)
ON CONFLICT DO NOTHING;

-- 'float': generic word vs insurance float. Active alias is 'insurance float'.
-- 'float' alone excluded to avoid matching unrelated technical contexts.
INSERT INTO rag_concept_aliases (concept_id, alias, is_active)
VALUES ('insurance_float', 'float', FALSE)
ON CONFLICT DO NOTHING;

-- ─────────────────────────────────────────────────────────────────────────────
-- CONCEPT ALIASES: psychology
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO rag_concept_aliases (concept_id, alias, is_active) VALUES
  ('mental_models',     'mental models',            TRUE),
  ('mental_models',     'mental model',             TRUE),
  ('mental_models',     'latticework',              TRUE),

  ('inversion',         'inversion',                TRUE),
  ('inversion',         'invert',                   TRUE),
  ('inversion',         'thinking backwards',       TRUE),

  ('incentives',        'incentives',               TRUE),
  ('incentives',        'incentive-caused bias',    TRUE),
  ('incentives',        'incentive superresponse',  TRUE),

  ('social_proof',      'social proof',             TRUE),

  ('loss_aversion',     'loss aversion',            TRUE),

  ('authority_bias',    'authority bias',           TRUE),

  ('availability_bias', 'availability bias',        TRUE),
  ('availability_bias', 'availability heuristic',   TRUE),

  ('lollapalooza',      'lollapalooza',             TRUE),
  ('lollapalooza',      'lollapalooza effect',      TRUE),

  ('temperament',       'temperament',              TRUE),
  ('temperament',       'investor temperament',     TRUE),

  ('mr_market',         'mr. market',               TRUE),
  ('mr_market',         'mr market',                TRUE)
ON CONFLICT DO NOTHING;

-- ─────────────────────────────────────────────────────────────────────────────
-- CONCEPT ALIASES: operations
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO rag_concept_aliases (concept_id, alias, is_active) VALUES
  ('management_quality', 'management quality',   TRUE),
  ('management_quality', 'management integrity', TRUE),

  ('corporate_culture',  'corporate culture',    TRUE),
  ('corporate_culture',  'company culture',      TRUE),

  ('owner_operator',     'owner-operator',       TRUE),
  ('owner_operator',     'owner operator',       TRUE),
  ('owner_operator',     'owner-managed',        TRUE)
ON CONFLICT DO NOTHING;

-- ─────────────────────────────────────────────────────────────────────────────
-- CONCEPT ALIASES: macro
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO rag_concept_aliases (concept_id, alias, is_active) VALUES
  ('inflation',             'inflation',              TRUE),
  ('inflation',             'inflationary',           TRUE),

  ('interest_rates',        'interest rates',         TRUE),
  ('interest_rates',        'interest rate',          TRUE),

  ('second_level_thinking', 'second level thinking',  TRUE),
  ('second_level_thinking', 'second-level thinking',  TRUE)
ON CONFLICT DO NOTHING;

-- ─────────────────────────────────────────────────────────────────────────────
-- CONCEPT ALIASES: additional valuation
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO rag_concept_aliases (concept_id, alias, is_active) VALUES
  ('free_cash_flow',    'free cash flow',              TRUE),
  ('free_cash_flow',    'fcf',                         TRUE),

  ('enterprise_value',  'enterprise value',            TRUE),
  ('enterprise_value',  'ev/ebitda',                   TRUE),

  ('return_on_equity',  'return on equity',            TRUE),
  ('return_on_equity',  'roe',                         TRUE),

  ('return_on_capital', 'return on invested capital',  TRUE),
  ('return_on_capital', 'roic',                        TRUE),
  ('return_on_capital', 'return on capital',           TRUE),

  ('earnings_yield',    'earnings yield',              TRUE),

  ('compound_interest', 'compound interest',           TRUE),
  ('compound_interest', 'compounding',                 TRUE),
  ('compound_interest', 'eighth wonder',               TRUE)
ON CONFLICT DO NOTHING;

-- ─────────────────────────────────────────────────────────────────────────────
-- CONCEPT ALIASES: additional investing
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO rag_concept_aliases (concept_id, alias, is_active) VALUES
  ('value_investing',  'value investing',              TRUE),
  ('value_investing',  'value investor',               TRUE),

  ('contrarian',       'contrarian',                   TRUE),
  ('contrarian',       'contrarian investing',         TRUE),

  ('patience',         'patience',                     TRUE),
  ('patience',         'long-term investor',           TRUE),

  ('risk_management',  'risk management',              TRUE),
  ('risk_management',  'downside protection',          TRUE),

  ('mean_reversion',   'mean reversion',               TRUE),
  ('mean_reversion',   'reversion to the mean',        TRUE)
ON CONFLICT DO NOTHING;
