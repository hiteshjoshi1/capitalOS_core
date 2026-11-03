"""#124: every IBKR stock holding is linked to an asset and the price job's symbol
map on import, so the price job fetches its quote."""

from __future__ import annotations

from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.portfolio.ibkr_flex import run_ibkr_flex_import_from_xml
from tests.test_ibkr_flex_phase1 import _seed_ibkr_account, _valid_flex_xml

_HK_AND_NEW_US = """
            <OpenPosition reportDate="2026-02-20" conid="952" symbol="700" description="TENCENT HOLDINGS LTD" assetCategory="STK" listingExchange="SEHK" currency="HKD" position="200" markPrice="380" positionValue="76000" positionValueInBase="13000" costBasisMoney="70000" costBasisMoneyInBase="12000" fxRateToBase="0.171" />
            <OpenPosition reportDate="2026-02-20" conid="953" symbol="ONON" description="ON HOLDING AG-CLASS A" assetCategory="STK" listingExchange="NYSE" currency="USD" position="50" markPrice="34" positionValue="1700" positionValueInBase="2295" costBasisMoney="1900" costBasisMoneyInBase="2565" fxRateToBase="1.35" />
            <OpenPosition reportDate="2026-02-20" conid="954" symbol="BRK B" description="BERKSHIRE HATHAWAY INC-CL B" assetCategory="STK" listingExchange="NYSE" currency="USD" position="5" markPrice="500" positionValue="2500" positionValueInBase="3375" costBasisMoney="2000" costBasisMoneyInBase="2700" fxRateToBase="1.35" />
            <OpenPosition reportDate="2026-02-20" conid="955" symbol="NVO   261127P00036000" description="NVO 27NOV26 36 P" assetCategory="OPT" listingExchange="CBOE" currency="USD" position="-1" markPrice="0.5" positionValue="-50" positionValueInBase="-67.5" costBasisMoney="-60" costBasisMoneyInBase="-81" fxRateToBase="1.35" />
"""


def _import(db_engine, tmp_path, monkeypatch, xml: str) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    db = sessionmaker(bind=db_engine)()
    try:
        run_ibkr_flex_import_from_xml(
            db, current_user_id=1, legacy_account_id=300, xml_text=xml, cutover_date=date(2026, 2, 1)
        )
    finally:
        db.close()


def _xml_with_more_positions() -> str:
    xml = _valid_flex_xml()
    marker = "</OpenPositions>"
    return xml.replace(marker, _HK_AND_NEW_US + "          " + marker, 1)


def test_import_links_every_stock_holding_to_a_priced_asset(db_engine, tmp_path, monkeypatch):
    _seed_ibkr_account(db_engine)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) VALUES "
                "(950, 'AAPL', 'Apple Inc.', 'STOCK', 'USD', 'US'), "
                "(951, '0700', 'Tencent', 'STOCK', 'HKD', 'HK'), "
                "(952, 'BRK-B', 'Berkshire', 'STOCK', 'USD', 'US')"
            )
        )
    _import(db_engine, tmp_path, monkeypatch, _xml_with_more_positions())

    with db_engine.connect() as conn:
        linked = dict(
            conn.execute(
                text("SELECT symbol, asset_id FROM broker_instruments WHERE platform_code = 'IBKR'")
            ).fetchall()
        )
        onon = conn.execute(
            text("SELECT id, name, asset_class, home_country FROM assets WHERE symbol = 'ONON' AND quote_currency = 'USD'")
        ).fetchone()
        maps = {
            (row[0], row[1], row[2])
            for row in conn.execute(text("SELECT asset_id, exchange_code, exchange_symbol FROM market_symbol_map")).fetchall()
        }

    assert linked["AAPL"] == 950  # existing asset, same symbol
    assert linked["700"] == 951  # IBKR "700" is the app's "0700"
    assert linked["BRK B"] == 952  # IBKR "BRK B" is the app's "BRK-B"
    assert onon is not None and onon[1] == "ON HOLDING AG-CLASS A" and onon[3] == "US"  # created
    assert linked["ONON"] == onon[0]
    assert linked["NVO   261127P00036000"] is None  # options aren't priced by the job
    assert (950, "US", "AAPL") in maps
    assert (951, "HKEX", "0700") in maps
    assert (952, "US", "BRK-B") in maps
    assert (onon[0], "US", "ONON") in maps


def test_reimport_is_idempotent(db_engine, tmp_path, monkeypatch):
    _seed_ibkr_account(db_engine)
    xml = _xml_with_more_positions()
    _import(db_engine, tmp_path, monkeypatch, xml)
    _import(db_engine, tmp_path, monkeypatch, xml)

    with db_engine.connect() as conn:
        assets = conn.execute(text("SELECT COUNT(*) FROM assets")).scalar()
        maps = conn.execute(text("SELECT COUNT(*) FROM market_symbol_map")).scalar()
    assert assets == 4  # AAPL, 700, ONON, BRK-B
    assert maps == 4
