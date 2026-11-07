-- #301: transaction notes held full card numbers (UOB/Citi card parsers wrote
-- "card_number=<16 digits>"; UOB bank GIRO lines carry the card number too). Mask every
-- account/card-like number in notes to its last 4 digits, the same rule as
-- app/ingestion/masking.py's mask_account_numbers (D-48), which now runs on new imports.
--
-- Only the parser's part of a note is touched: the runner's " | fp:<64 hex>" suffix (or a
-- bare "fp:<hash>") is kept byte for byte. Notes are not part of the dedup key or the
-- fingerprint (D-35), so re-importing a file after this adds no rows.
-- Idempotent: an already-masked number ("************1234") is not a token again.

CREATE OR REPLACE FUNCTION pg_temp.capitalos_mask_token(tok text) RETURNS text
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
  symbols int := 0;
  last4 text := '';
  keep int := 4;
  out text := '';
  c text;
  k int;
BEGIN
  FOR k IN REVERSE length(tok)..1 LOOP
    c := substr(tok, k, 1);
    IF c NOT IN (' ', '-') THEN
      symbols := symbols + 1;
      IF length(last4) < 4 THEN last4 := c || last4; END IF;
    END IF;
  END LOOP;
  -- Shorter runs are amounts, years, codes; dash dates are not numbers.
  IF symbols < 8 OR last4 !~ '^[0-9]{4}$'
     OR tok ~ '^([0-9]{4}-[0-9]{1,2}-[0-9]{1,2}|[0-9]{1,2}-[0-9]{1,2}-[0-9]{4})$' THEN
    RETURN tok;
  END IF;
  FOR k IN REVERSE length(tok)..1 LOOP
    c := substr(tok, k, 1);
    IF c IN (' ', '-') THEN
      out := c || out;
    ELSIF keep > 0 THEN
      out := c || out;
      keep := keep - 1;
    ELSE
      out := '*' || out;
    END IF;
  END LOOP;
  RETURN out;
END;
$$;

-- The tokens of masking.py's _TOKEN_RE: a digit not after [A-Za-z0-9*], then digits / X / *
-- or a single space or dash before one, ending on a digit not followed by [A-Za-z0-9*].
CREATE OR REPLACE FUNCTION pg_temp.capitalos_mask_numbers(t text) RETURNS text
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
  n int := length(t);
  i int := 1;
  j int;
  k int;
  best int;
  out text := '';
  prev text;
BEGIN
  IF t IS NULL OR t = '' THEN RETURN t; END IF;
  WHILE i <= n LOOP
    prev := CASE WHEN i > 1 THEN substr(t, i - 1, 1) ELSE '' END;
    IF substr(t, i, 1) ~ '[0-9]' AND prev !~ '[A-Za-z0-9*]' THEN
      j := i;  -- the longest run
      LOOP
        EXIT WHEN j + 1 > n;
        IF substr(t, j + 1, 1) ~ '[0-9Xx*]' THEN
          j := j + 1;
        ELSIF substr(t, j + 1, 1) IN (' ', '-') AND j + 2 <= n AND substr(t, j + 2, 1) ~ '[0-9Xx*]' THEN
          j := j + 2;
        ELSE
          EXIT;
        END IF;
      END LOOP;
      best := NULL;  -- the longest prefix ending on a digit not followed by [A-Za-z0-9*]
      FOR k IN REVERSE j..i LOOP
        IF substr(t, k, 1) ~ '[0-9]' AND (k = n OR substr(t, k + 1, 1) !~ '[A-Za-z0-9*]') THEN
          best := k;
          EXIT;
        END IF;
      END LOOP;
      IF best IS NULL THEN
        out := out || substr(t, i, 1);
        i := i + 1;
      ELSE
        out := out || pg_temp.capitalos_mask_token(substr(t, i, best - i + 1));
        i := best + 1;
      END IF;
    ELSE
      out := out || substr(t, i, 1);
      i := i + 1;
    END IF;
  END LOOP;
  RETURN out;
END;
$$;

-- The parser's part of a note, masked; the fp suffix as it was.
CREATE OR REPLACE FUNCTION pg_temp.capitalos_mask_note(note text) RETURNS text
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
  head text;
BEGIN
  IF note IS NULL OR note ~ '^fp:[0-9a-f]{64}$' THEN RETURN note; END IF;
  head := substring(note FROM '^(.*) \| fp:[0-9a-f]{64}$');
  IF head IS NOT NULL THEN
    RETURN pg_temp.capitalos_mask_numbers(head) || substr(note, length(head) + 1);
  END IF;
  RETURN pg_temp.capitalos_mask_numbers(note);
END;
$$;

UPDATE transactions
SET notes = pg_temp.capitalos_mask_note(notes)
WHERE notes ~ '[0-9]{4}'
  AND notes IS DISTINCT FROM pg_temp.capitalos_mask_note(notes);
