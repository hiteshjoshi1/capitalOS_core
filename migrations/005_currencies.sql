CREATE TABLE IF NOT EXISTS currencies (
  id        BIGSERIAL PRIMARY KEY,
  code      TEXT NOT NULL UNIQUE,
  name      TEXT,
  country   TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE currencies
  ADD COLUMN IF NOT EXISTS country TEXT;

INSERT INTO currencies (code, name, country) VALUES
  ('USD', 'U.S. Dollar', 'United States'),
  ('EUR', 'Euro', 'European Union (Eurozone)'),
  ('JPY', 'Japanese Yen', 'Japan'),
  ('GBP', 'British Pound', 'United Kingdom'),
  ('CNY', 'Chinese Renminbi (Yuan)', 'China'),
  ('AUD', 'Australian Dollar', 'Australia'),
  ('CAD', 'Canadian Dollar', 'Canada'),
  ('CHF', 'Swiss Franc', 'Switzerland'),
  ('HKD', 'Hong Kong Dollar', 'Hong Kong (SAR)'),
  ('NZD', 'New Zealand Dollar', 'New Zealand'),
  ('INR', 'Indian Rupee', 'India'),
  ('IDR', 'Indonesian Rupiah', 'Indonesia'),
  ('PKR', 'Pakistani Rupee', 'Pakistan'),
  ('NGN', 'Nigerian Naira', 'Nigeria'),
  ('BRL', 'Brazilian Real', 'Brazil'),
  ('BDT', 'Bangladeshi Taka', 'Bangladesh'),
  ('RUB', 'Russian Ruble', 'Russia'),
  ('MXN', 'Mexican Peso', 'Mexico'),
  ('ETB', 'Ethiopian Birr', 'Ethiopia'),
  ('PHP', 'Philippine Peso', 'Philippines'),
  ('VND', 'Vietnamese Dong', 'Vietnam'),
  ('THB', 'Thai Baht', 'Thailand'),
  ('MYR', 'Malaysian Ringgit', 'Malaysia'),
  ('SGD', 'Singapore Dollar', 'Singapore'),
  ('KRW', 'South Korean Won', 'South Korea'),
  ('EGP', 'Egyptian Pound', 'Egypt'),
  ('IRR', 'Iranian Rial', 'Iran'),
  ('TRY', 'Turkish Lira', 'Turkey'),
  ('SAR', 'Saudi Riyal', 'Saudi Arabia'),
  ('AED', 'UAE Dirham', 'United Arab Emirates'),
  ('IQD', 'Iraqi Dinar', 'Iraq'),
  ('ILS', 'Israeli New Shekel', 'Israel'),
  ('COP', 'Colombian Peso', 'Colombia'),
  ('ARS', 'Argentine Peso', 'Argentina'),
  ('PEN', 'Peruvian Sol', 'Peru'),
  ('CLP', 'Chilean Peso', 'Chile'),
  ('VES', 'Venezuelan Bolívar', 'Venezuela'),
  ('CDF', 'Congolese Franc', 'DR Congo'),
  ('TZS', 'Tanzanian Shilling', 'Tanzania'),
  ('ZAR', 'South African Rand', 'South Africa')
ON CONFLICT (code) DO NOTHING;
