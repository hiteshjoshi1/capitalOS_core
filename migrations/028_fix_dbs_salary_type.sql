UPDATE transactions
SET type = 'INCOME',
    category = 'Salary'
WHERE id IN (
  SELECT t.id
  FROM transactions t
  LEFT JOIN accounts a ON a.id = t.account_id
  WHERE t.type = 'TRANSFER'
    AND t.amount > 0
    AND (
      UPPER(COALESCE(t.source, '')) IN ('DBS', 'POSB')
      OR UPPER(COALESCE(a.platform, '')) IN ('DBS', 'POSB')
    )
    AND (
      UPPER(COALESCE(t.merchant_counterparty, '')) LIKE '%SALARY%'
      OR UPPER(COALESCE(t.notes, '')) LIKE '%SALARY%'
      OR UPPER(COALESCE(t.merchant_counterparty, '') || ' ' || COALESCE(t.notes, '')) LIKE '%PAYROLL%'
      OR (
        (
          UPPER(COALESCE(t.merchant_counterparty, '') || ' ' || COALESCE(t.notes, '')) LIKE 'PAY %'
          OR UPPER(COALESCE(t.merchant_counterparty, '') || ' ' || COALESCE(t.notes, '')) LIKE '% PAY %'
        )
        AND (
          UPPER(COALESCE(t.merchant_counterparty, '') || ' ' || COALESCE(t.notes, '')) LIKE '%PTE%'
          OR UPPER(COALESCE(t.merchant_counterparty, '') || ' ' || COALESCE(t.notes, '')) LIKE '%LTD%'
          OR UPPER(COALESCE(t.merchant_counterparty, '') || ' ' || COALESCE(t.notes, '')) LIKE '%LIMITED%'
          OR UPPER(COALESCE(t.merchant_counterparty, '') || ' ' || COALESCE(t.notes, '')) LIKE '%INC%'
          OR UPPER(COALESCE(t.merchant_counterparty, '') || ' ' || COALESCE(t.notes, '')) LIKE '%COMPANY%'
        )
      )
    )
    AND UPPER(COALESCE(t.merchant_counterparty, '') || ' ' || COALESCE(t.notes, '')) NOT LIKE '%IBKR%'
    AND UPPER(COALESCE(t.merchant_counterparty, '') || ' ' || COALESCE(t.notes, '')) NOT LIKE '%INTERACTIVE BROKERS%'
    AND UPPER(COALESCE(t.merchant_counterparty, '') || ' ' || COALESCE(t.notes, '')) NOT LIKE '%COINBASE%'
    AND UPPER(COALESCE(t.merchant_counterparty, '') || ' ' || COALESCE(t.notes, '')) NOT LIKE '%UOB%'
    AND UPPER(COALESCE(t.merchant_counterparty, '') || ' ' || COALESCE(t.notes, '')) NOT LIKE '%OCBC%'
    AND UPPER(COALESCE(t.merchant_counterparty, '') || ' ' || COALESCE(t.notes, '')) NOT LIKE '%DBS VICKERS%'
    AND UPPER(COALESCE(t.merchant_counterparty, '') || ' ' || COALESCE(t.notes, '')) NOT LIKE '%POSB%'
);

DELETE FROM category_overrides
WHERE source = 'rule'
  AND transaction_id IN (
    SELECT t.id
    FROM transactions t
    LEFT JOIN accounts a ON a.id = t.account_id
    WHERE t.type = 'INCOME'
      AND t.amount > 0
      AND t.category = 'Salary'
      AND (
        UPPER(COALESCE(t.source, '')) IN ('DBS', 'POSB')
        OR UPPER(COALESCE(a.platform, '')) IN ('DBS', 'POSB')
      )
  )
  AND category_id IN (
    SELECT child.id
    FROM category_taxonomy child
    LEFT JOIN category_taxonomy parent ON parent.id = child.parent_id
    WHERE LOWER(COALESCE(child.code, '')) = 'transfer'
       OR LOWER(COALESCE(parent.code, '')) = 'transfer'
  );
