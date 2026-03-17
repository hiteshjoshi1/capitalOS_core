from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import text


_MIGRATION_SQL_FALLBACK = """
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
"""


def _migration_sql() -> str:
    candidates = [
        Path(__file__).resolve().parents[2] / "migrations" / "028_fix_dbs_salary_type.sql",
        Path("/app/migrations/028_fix_dbs_salary_type.sql"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    return _MIGRATION_SQL_FALLBACK


def _run_migration(db_engine) -> None:
    conn = db_engine.raw_connection()
    try:
        conn.executescript(_migration_sql())
        conn.commit()
    finally:
        conn.close()


def test_dbs_salary_backfill_is_idempotent_and_restores_cash_flow(
    client: TestClient,
    db_engine,
):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country) VALUES "
                "(1, 'DBS Savings', 'DBS', 'BANK', 'SGD', 'SG')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO category_taxonomy (id, code, name, parent_id, display_order) VALUES "
                "(100, 'transfer', 'Transfer', NULL, 100), "
                "(101, 'transfer_internal', 'Internal Transfer', 100, 101)"
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO transactions
                  (id, ts, account_id, amount, type, currency, category, merchant_counterparty, notes, source)
                VALUES
                  (1, '2026-02-05 00:00:00+00:00', 1, 5000, 'TRANSFER', 'SGD', 'Bank::GR',
                   'PAY PARTIOR PTE. LTD.', 'IBG SALARY FEB 2026', 'DBS'),
                  (2, '2026-02-06 00:00:00+00:00', 1, 900, 'TRANSFER', 'SGD', 'Bank::ADV',
                   'Transfer to IBKR', 'Brokerage top up', 'DBS')
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO category_overrides (id, transaction_id, category_id, source, rule_id)
                VALUES (1, 1, 101, 'rule', NULL)
                """
            )
        )

    before = client.get("/spending/cash-flow-detail?month=2026-02&base_currency=SGD")
    assert before.status_code == 200
    assert before.json()["income_total"] == 0.0

    _run_migration(db_engine)
    _run_migration(db_engine)

    with db_engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, type, category
                FROM transactions
                ORDER BY id
                """
            )
        ).mappings().all()
        overrides = conn.execute(
            text("SELECT COUNT(*) AS count FROM category_overrides WHERE transaction_id = 1")
        ).mappings().one()

    assert [dict(row) for row in rows] == [
        {"id": 1, "type": "INCOME", "category": "Salary"},
        {"id": 2, "type": "TRANSFER", "category": "Bank::ADV"},
    ]
    assert overrides["count"] == 0

    after = client.get("/spending/cash-flow-detail?month=2026-02&base_currency=SGD")
    assert after.status_code == 200
    payload = after.json()

    assert payload["income_total"] == 5000.0
    assert payload["income"]["transaction_count"] == 1
    assert payload["income"]["transactions"][0]["merchant_counterparty"] == "PAY PARTIOR PTE. LTD."
    assert payload["income"]["transactions"][0]["resolved_category"] == "Salary"
