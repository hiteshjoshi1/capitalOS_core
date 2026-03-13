INSERT INTO parser_registry (format_signature, parser_key, version)
VALUES (
  '4074417c4582687ecaeaeb5f0e8e6dda8a4bde42d801d613ef77d1852c912ef5',
  'uob_credit_card_xls_v1',
  1
)
ON CONFLICT (format_signature) DO NOTHING;
