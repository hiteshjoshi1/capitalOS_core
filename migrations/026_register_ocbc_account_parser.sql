INSERT INTO parser_registry (format_signature, parser_key, version)
VALUES (
  '49291988f2110dd6431bf71a286f2192c98fba692608468006d052b33022423f',
  'ocbc_account_csv_v1',
  1
)
ON CONFLICT (format_signature) DO NOTHING;
