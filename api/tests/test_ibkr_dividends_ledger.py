"""#113: IBKR Statement of Funds lines reach the cash ledger, and the Dividends
page reads dividend / withholding lines from it."""

from __future__ import annotations

from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.portfolio.ibkr_flex import parse_flex_statement, run_ibkr_flex_import_from_xml
from tests.test_ibkr_flex_phase1 import _seed_ibkr_account


def _flex_xml(from_date: str, to_date: str, report_date: str, extra_funds: str = "") -> str:
    # Shaped like a real Flex response: one <StmtFunds> section holding
    # <StatementOfFundsLine> rows in the base currency (SGD).
    return f"""
    <FlexQueryResponse queryName="CapitalOS Daily Portfolio" type="AF">
      <FlexStatements count="1">
        <FlexStatement accountId="U1" fromDate="{from_date}" toDate="{to_date}" period="Last30CalendarDays" whenGenerated="20261102;195458">
          <EquitySummaryInBase>
            <EquitySummaryByReportDateInBase accountId="U1" reportDate="{report_date}" cash="1000" stock="5000" options="0" funds="0" bonds="0" interestAccruals="0" dividendAccruals="0" total="6000" />
          </EquitySummaryInBase>
          <CashReport>
            <CashReportCurrency currency="BASE_SUMMARY" toDate="{report_date}" endingCash="1000" />
          </CashReport>
          <OpenPositions>
            <OpenPosition accountId="U1" reportDate="{report_date}" conid="2956358" symbol="291" description="CHINA RESOURCES BEER HOLDING" assetCategory="STK" listingExchange="SEHK" currency="HKD" position="7000" markPrice="4.38" positionValue="30660" positionValueInBase="5000" costBasisMoney="30000" costBasisMoneyInBase="4900" fxRateToBase="0.16293" />
          </OpenPositions>
          <ConversionRates>
            <ConversionRate reportDate="{report_date}" fromCurrency="HKD" toCurrency="SGD" rate="0.16293" />
          </ConversionRates>
          <StmtFunds>
            <StatementOfFundsLine accountId="U1" currency="SGD" assetCategory="STK" symbol="291" description="CHINA RESOURCES BEER HOLDING" conid="2956358" reportDate="20261021" date="20261021" activityCode="DIV" activityDescription="291 (HK0291001490) Cash Dividend HKD 0.516 (Ordinary Dividend)" debit="" credit="587.99748" amount="587.99748" balance="126032.97" transactionID="1004513765" />
            <StatementOfFundsLine accountId="U1" currency="SGD" assetCategory="" symbol="" description="" conid="" reportDate="20261021" date="20261021" activityCode="ADJ" activityDescription="FX Translations P&amp;L" debit="-1.5" credit="" amount="-1.5" balance="126031.47" transactionID="" />
            {extra_funds}
          </StmtFunds>
          <Trades />
          <CorporateActions />
        </FlexStatement>
      </FlexStatements>
    </FlexQueryResponse>
    """


_US_DIVIDEND = """
            <StatementOfFundsLine accountId="U1" currency="SGD" assetCategory="STK" symbol="AAPL" description="APPLE INC" conid="265598" reportDate="20261023" date="20261023" activityCode="DIV" activityDescription="AAPL(US0378331005) Cash Dividend USD 0.26 per Share (Ordinary Dividend)" amount="13.5" transactionID="1004600001" />
            <StatementOfFundsLine accountId="U1" currency="SGD" assetCategory="STK" symbol="AAPL" description="APPLE INC" conid="265598" reportDate="20261023" date="20261023" activityCode="FRTAX" activityDescription="AAPL(US0378331005) Cash Dividend USD 0.26 per Share - US Tax" amount="-4.05" transactionID="1004600002" />
"""


def _import(db_engine, tmp_path, monkeypatch, *xmls: str) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    db = sessionmaker(bind=db_engine)()
    try:
        for i, xml in enumerate(xmls):
            run_ibkr_flex_import_from_xml(
                db,
                current_user_id=1,
                legacy_account_id=300,
                xml_text=xml,
                cutover_date=date(2026, 10, 1),
                reference_code=f"REF{i}",
            )
    finally:
        db.close()


def test_parser_reads_statement_of_funds_lines_with_their_security():
    statement = parse_flex_statement(_flex_xml("20261001", "20261030", "20261030"))

    codes = [entry.activity_code for entry in statement.cash_ledger_entries]
    assert codes == ["DIV", "ADJ"]
    dividend = statement.cash_ledger_entries[0]
    assert dividend.activity_date == date(2026, 10, 21)
    assert dividend.currency == "SGD"
    assert str(dividend.amount) == "587.99748"
    assert dividend.description.startswith("291 (HK0291001490) Cash Dividend")
    assert dividend.broker_activity_id == "1004513765"
    assert dividend.security == {
        "conid": "2956358",
        "symbol": "291",
        "security_description": "CHINA RESOURCES BEER HOLDING",
        "asset_category": "STK",
    }
    adjustment = statement.cash_ledger_entries[1]
    assert adjustment.broker_activity_id is None
    assert adjustment.security == {}


def test_overlapping_30_day_reports_store_each_cash_line_once(db_engine, tmp_path, monkeypatch):
    _seed_ibkr_account(db_engine)
    _import(
        db_engine,
        tmp_path,
        monkeypatch,
        _flex_xml("20261001", "20261030", "20261030"),
        _flex_xml("20261004", "20261102", "20261102", _US_DIVIDEND),
    )

    with db_engine.connect() as conn:
        rows = conn.execute(
            text("SELECT activity_code, broker_activity_id FROM portfolio_cash_ledger_entries ORDER BY id")
        ).fetchall()
    assert sorted((r[0], r[1]) for r in rows) == sorted(
        [("DIV", "1004513765"), ("ADJ", None), ("DIV", "1004600001"), ("FRTAX", "1004600002")]
    )


def test_dividends_page_reads_ibkr_dividends_from_the_ledger(client, db_engine, tmp_path, monkeypatch):
    _seed_ibkr_account(db_engine)
    _import(db_engine, tmp_path, monkeypatch, _flex_xml("20261004", "20261102", "20261102", _US_DIVIDEND))

    summary = client.get(
        "/dividends/summary",
        params={"from_month": "2026-10", "to_month": "2026-10", "base_currency": "SGD", "period": "month"},
    )
    assert summary.status_code == 200, summary.text
    totals = summary.json()["totals"]
    assert round(totals["gross"], 5) == round(587.99748 + 13.5, 5)
    assert round(totals["withholding"], 5) == 4.05
    assert round(totals["net_received"], 5) == round(587.99748 + 13.5 - 4.05, 5)

    companies = client.get(
        "/dividends/by-company",
        params={"from_month": "2026-10", "to_month": "2026-10", "base_currency": "SGD"},
    )
    assert companies.status_code == 200, companies.text
    by_symbol = {item["symbol"]: item for item in companies.json()["items"]}
    assert by_symbol["291"]["company"] == "CHINA RESOURCES BEER HOLDING"
    assert by_symbol["291"]["country"] == "HK"  # from the instrument's SEHK listing
    assert round(by_symbol["AAPL"]["withholding"], 5) == 4.05

    history = client.get("/dividends/history", params={"symbol": "291", "from_month": "2026-10", "to_month": "2026-10"})
    assert history.status_code == 200, history.text
    assert [event["month"] for event in history.json()["events"]] == ["2026-10"]


def test_ledger_replaces_transactions_rows_for_the_same_account(client, db_engine, tmp_path, monkeypatch):
    _seed_ibkr_account(db_engine)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO transactions (id, ts, account_id, amount, type, currency, category, merchant_counterparty, source)
                VALUES
                  (701, '2026-09-10T00:00:00+00:00', 300, 50, 'INCOME', 'SGD', 'Brokerage::Dividend', 'OLD CSV DIVIDEND', 'IBKR'),
                  (702, '2026-10-21T00:00:00+00:00', 300, 587.99748, 'INCOME', 'SGD', 'Brokerage::Dividend', '291 DIVIDEND', 'IBKR')
                """
            )
        )
    _import(db_engine, tmp_path, monkeypatch, _flex_xml("20261001", "20261030", "20261030"))

    summary = client.get(
        "/dividends/summary",
        params={"from_month": "2026-09", "to_month": "2026-10", "base_currency": "SGD", "period": "month"},
    )
    assert summary.status_code == 200, summary.text
    by_bucket = {bucket["bucket"]: bucket["gross"] for bucket in summary.json()["buckets"]}
    # September predates the ledger's first line, so the CSV row still counts; the
    # October CSV row is the same dividend as the ledger line and is not doubled.
    assert by_bucket == {"2026-09": 50.0, "2026-10": 587.99748}


def test_identical_cash_lines_in_one_report_are_both_kept(db_engine, tmp_path, monkeypatch):
    # Two id-less lines with the same values are two lines (#157): both are kept,
    # and importing the same report again (or an overlapping one) doesn't add more.
    _seed_ibkr_account(db_engine)
    duplicate = (
        '<StatementOfFundsLine currency="SGD" date="20261022" activityCode="ADJ" '
        'activityDescription="FX Translations P&amp;L" amount="2.0" transactionID="" />'
    )
    _import(
        db_engine,
        tmp_path,
        monkeypatch,
        _flex_xml("20261001", "20261030", "20261030", duplicate + duplicate),
        _flex_xml("20261004", "20261102", "20261102", duplicate + duplicate),
    )

    with db_engine.connect() as conn:
        count = conn.execute(
            text("SELECT COUNT(*) FROM portfolio_cash_ledger_entries WHERE activity_date = '2026-10-22'")
        ).scalar()
    assert count == 2
