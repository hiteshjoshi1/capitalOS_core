INSERT INTO parser_registry (format_signature, parser_key, version)
VALUES (
  'd1c0671074fd18feb91e5a23d826222e9af69de50702f92ca3d4052bf7c8596e',
  'citi_credit_card_csv_v1',
  1
)
ON CONFLICT (format_signature) DO NOTHING;
