INSERT INTO parser_registry (format_signature, parser_key, version)
VALUES ('ee7cf0a7a7cb03f496c2cb50df201b899b15d964cb6acc408c2342371c6f2b4d', 'dbs_vickers_holdings_xls_v1', 1)
ON CONFLICT (format_signature) DO NOTHING;
