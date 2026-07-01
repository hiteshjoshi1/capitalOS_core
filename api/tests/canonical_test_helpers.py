from datetime import date, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.portfolio.legacy_backfill import backfill_legacy_positions


def backfill_legacy_positions_for_test(db_engine, *, current_user_id: int = 1) -> None:
    db = Session(bind=db_engine)
    try:
        backfill_legacy_positions(db, current_user_id=current_user_id)
    finally:
        db.close()


def _as_date(value: date | datetime | str) -> date | str:
    if isinstance(value, datetime):
        return value.date()
    return value


def _canonical_broker_ids(conn, account_id: int, platform_code: str | None, base_currency: str | None) -> tuple[int, int]:
    account = conn.execute(
        text("SELECT platform, currency, user_id FROM accounts WHERE id = :account_id"),
        {"account_id": account_id},
    ).mappings().one()
    platform = (platform_code or account.get("platform") or "TEST").upper()
    currency = (base_currency or account.get("currency") or "USD").upper()
    user_id = int(account.get("user_id") or 1)

    connection = conn.execute(
        text(
            """
            SELECT id FROM broker_connections
            WHERE user_id = :user_id AND platform_code = :platform_code
            ORDER BY id
            LIMIT 1
            """
        ),
        {"user_id": user_id, "platform_code": platform},
    ).mappings().one_or_none()
    if connection:
        connection_id = int(connection["id"])
    else:
        result = conn.execute(
            text(
                """
                INSERT INTO broker_connections
                  (user_id, platform_code, connection_type, display_name, status, metadata_json)
                VALUES
                  (:user_id, :platform_code, 'test_fixture', :display_name, 'active', '{}')
                """
            ),
            {"user_id": user_id, "platform_code": platform, "display_name": f"{platform} Fixture"},
        )
        connection_id = int(result.lastrowid)

    broker_account_key = f"fixture:{account_id}"
    broker_account = conn.execute(
        text(
            """
            SELECT id FROM broker_accounts
            WHERE connection_id = :connection_id AND broker_account_id = :broker_account_id
            """
        ),
        {"connection_id": connection_id, "broker_account_id": broker_account_key},
    ).mappings().one_or_none()
    if broker_account:
        broker_account_id = int(broker_account["id"])
    else:
        result = conn.execute(
            text(
                """
                INSERT INTO broker_accounts
                  (connection_id, legacy_account_id, broker_account_id, base_currency, status, metadata_json)
                VALUES
                  (:connection_id, :legacy_account_id, :broker_account_id, :base_currency, 'active', '{}')
                """
            ),
            {
                "connection_id": connection_id,
                "legacy_account_id": account_id,
                "broker_account_id": broker_account_key,
                "base_currency": currency,
            },
        )
        broker_account_id = int(result.lastrowid)
    return broker_account_id, connection_id


def seed_canonical_position_snapshot_for_test(
    db_engine,
    *,
    account_id: int,
    asset_id: int,
    as_of: date | datetime | str,
    quantity: float,
    market_value_base: float,
    market_price: float | None = None,
    cost_basis_base: float | None = None,
    currency: str | None = None,
    platform_code: str | None = None,
    authority_status: str = "authoritative",
    metadata_json: str = "{}",
) -> None:
    with db_engine.begin() as conn:
        account = conn.execute(
            text("SELECT platform, currency FROM accounts WHERE id = :account_id"),
            {"account_id": account_id},
        ).mappings().one()
        asset = conn.execute(
            text("SELECT symbol, name, asset_class, quote_currency FROM assets WHERE id = :asset_id"),
            {"asset_id": asset_id},
        ).mappings().one()
        platform = (platform_code or account.get("platform") or "TEST").upper()
        row_currency = (currency or asset.get("quote_currency") or account.get("currency") or "USD").upper()
        broker_account_id, _connection_id = _canonical_broker_ids(
            conn,
            account_id,
            platform,
            str(account.get("currency") or row_currency),
        )
        instrument = conn.execute(
            text(
                """
                SELECT id FROM broker_instruments
                WHERE platform_code = :platform_code
                  AND broker_instrument_id = :broker_instrument_id
                  AND COALESCE(currency, '') = :currency
                """
            ),
            {"platform_code": platform, "broker_instrument_id": f"asset:{asset_id}", "currency": row_currency},
        ).mappings().one_or_none()
        if instrument:
            broker_instrument_id = int(instrument["id"])
        else:
            result = conn.execute(
                text(
                    """
                    INSERT INTO broker_instruments
                      (platform_code, broker_instrument_id, asset_id, symbol, description, security_type, currency, metadata_json)
                    VALUES
                      (:platform_code, :broker_instrument_id, :asset_id, :symbol, :description, :security_type, :currency, '{}')
                    """
                ),
                {
                    "platform_code": platform,
                    "broker_instrument_id": f"asset:{asset_id}",
                    "asset_id": asset_id,
                    "symbol": asset.get("symbol"),
                    "description": asset.get("name") or asset.get("symbol"),
                    "security_type": asset.get("asset_class") or "STOCK",
                    "currency": row_currency,
                },
            )
            broker_instrument_id = int(result.lastrowid)

        result = conn.execute(
            text(
                """
                INSERT INTO broker_import_runs
                  (broker_account_id, legacy_account_id, platform_code, source_type, import_scope, status, metadata_json)
                VALUES
                  (:broker_account_id, :legacy_account_id, :platform_code, 'test_fixture', 'daily', 'completed', '{}')
                """
            ),
            {"broker_account_id": broker_account_id, "legacy_account_id": account_id, "platform_code": platform},
        )
        import_run_id = int(result.lastrowid)
        report_date = _as_date(as_of)
        price = market_price
        if price is None and quantity:
            price = float(market_value_base) / float(quantity)
        conn.execute(
            text(
                """
                INSERT INTO portfolio_position_snapshots
                  (broker_account_id, legacy_account_id, broker_instrument_id, import_run_id, report_date,
                   quantity, currency, market_price, market_value_local, market_value_base,
                   cost_basis_local, cost_basis_base, fx_rate_to_base, authority_status, metadata_json)
                VALUES
                  (:broker_account_id, :legacy_account_id, :broker_instrument_id, :import_run_id, :report_date,
                   :quantity, :currency, :market_price, :market_value_local, :market_value_base,
                   :cost_basis_local, :cost_basis_base, 1, :authority_status, :metadata_json)
                """
            ),
            {
                "broker_account_id": broker_account_id,
                "legacy_account_id": account_id,
                "broker_instrument_id": broker_instrument_id,
                "import_run_id": import_run_id,
                "report_date": report_date,
                "quantity": quantity,
                "currency": row_currency,
                "market_price": price,
                "market_value_local": market_value_base,
                "market_value_base": market_value_base,
                "cost_basis_local": cost_basis_base if cost_basis_base is not None else market_value_base,
                "cost_basis_base": cost_basis_base if cost_basis_base is not None else market_value_base,
                "authority_status": authority_status,
                "metadata_json": metadata_json,
            },
        )


def seed_canonical_account_balance_for_test(
    db_engine,
    *,
    account_id: int,
    as_of: date | datetime | str,
    currency: str,
    balance_base: float,
    balance_local: float | None = None,
    balance_type: str = "bank_cash",
    source_kind: str = "test_fixture",
) -> None:
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO account_balance_snapshots
                  (account_id, as_of_date, currency, balance_type, balance_local, balance_base,
                   fx_rate_to_base, authority_status, source_kind, metadata_json)
                VALUES
                  (:account_id, :as_of_date, :currency, :balance_type, :balance_local, :balance_base,
                   1, 'authoritative', :source_kind, '{}')
                """
            ),
            {
                "account_id": account_id,
                "as_of_date": _as_date(as_of),
                "currency": currency.upper(),
                "balance_type": balance_type,
                "balance_local": balance_local if balance_local is not None else balance_base,
                "balance_base": balance_base,
                "source_kind": source_kind,
            },
        )
