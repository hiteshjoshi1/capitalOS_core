from pathlib import Path

from app.ingestion.parsers.dbs_transaction_history_csv_v1 import parse_dbs_transaction_history_csv
from app.ingestion.parsers.ibkr_activity_csv_v1 import parse_ibkr_activity_csv
from app.ingestion.parsers.ocbc_account_csv_v1 import parse_ocbc_account_csv
from app.ingestion.parsers.sharekhan_holdings_xls_v1 import parse_sharekhan_holdings_xls


def _write_dbs_fixture(tmp_path: Path, name: str, row: str) -> Path:
    content = (
        "Account Details For:,DBS Multiplier\n"
        "Statement as at:,19 Feb 2026\n"
        "Currency:,SGD - Singapore Dollar\n"
        "Available Balance:,SGD 1000.00\n"
        "Ledger Balance:,SGD 900.00\n"
        "Transaction Date,Value Date,Statement Code,Description,Supplementary Code,Supplementary Code Description,"
        "Client Reference,Additional Reference,Status,Currency,Debit Amount,Credit Amount\n"
        f"{row}\n"
    )
    fixture = tmp_path / name
    fixture.write_text(content, encoding="utf-8")
    return fixture


def test_dbs_parser_extracts_cash_and_transactions(tmp_path: Path):
    fixture = _write_dbs_fixture(
        tmp_path,
        "dbs.csv",
        "19 Feb 2026,19 Feb 2026,GR,Salary,IBG,Payments,REF,OTHR,Settled,SGD,,500",
    )
    result = parse_dbs_transaction_history_csv(str(fixture))
    assert len(result.transactions) == 1
    assert result.transactions[0]["type"] == "INCOME"
    assert result.transactions[0]["category"] == "Salary"
    assert result.positions
    assert result.positions[0]["asset_class"] == "CASH"


def test_dbs_parser_marks_transfers(tmp_path: Path):
    fixture = _write_dbs_fixture(
        tmp_path,
        "dbs_transfer.csv",
        "19 Feb 2026,19 Feb 2026,ADV,TRF FT251009IB00249524,IBG,Payments,REF,OTHR,Settled,SGD,10000,",
    )

    result = parse_dbs_transaction_history_csv(str(fixture))
    assert len(result.transactions) == 1
    assert result.transactions[0]["type"] == "TRANSFER"


def test_dbs_parser_prefers_transaction_date(tmp_path: Path):
    fixture = _write_dbs_fixture(
        tmp_path,
        "dbs_dates.csv",
        "18 Feb 2026,19 Feb 2026,GR,Salary,IBG,Payments,REF,OTHR,Settled,SGD,,500",
    )

    result = parse_dbs_transaction_history_csv(str(fixture))
    assert len(result.transactions) == 1
    assert result.transactions[0]["ts"].date().isoformat() == "2026-02-18"
    assert result.positions[0]["currency"] == "SGD"


def test_dbs_parser_keeps_salary_giro_credit_as_income(tmp_path: Path):
    fixture = _write_dbs_fixture(
        tmp_path,
        "dbs_salary_giro.csv",
        "19 Feb 2026,19 Feb 2026,GR,PAY PARTIOR PTE. LTD.,GIRO,SALARY FEB 2026,REF,OTHR,Settled,SGD,,7800",
    )

    result = parse_dbs_transaction_history_csv(str(fixture))

    assert result.transactions[0]["type"] == "INCOME"
    assert result.transactions[0]["category"] == "Salary"


def test_dbs_parser_keeps_salary_ibg_credit_as_income(tmp_path: Path):
    fixture = _write_dbs_fixture(
        tmp_path,
        "dbs_salary_ibg.csv",
        "19 Feb 2026,19 Feb 2026,GR,PAY PARTIOR PTE. LTD. SALARY_MAR,IBG,Payroll credit,REF,OTHR,Settled,SGD,,7800",
    )

    result = parse_dbs_transaction_history_csv(str(fixture))

    assert result.transactions[0]["type"] == "INCOME"
    assert result.transactions[0]["category"] == "Salary"


def test_dbs_parser_marks_non_salary_giro_self_transfer(tmp_path: Path):
    fixture = _write_dbs_fixture(
        tmp_path,
        "dbs_giro_transfer.csv",
        "19 Feb 2026,19 Feb 2026,ADV,GIRO TO UOB ONE ACCOUNT,IBG,Savings transfer,REF,OTHR,Settled,SGD,500,",
    )

    result = parse_dbs_transaction_history_csv(str(fixture))

    assert result.transactions[0]["type"] == "TRANSFER"


def test_dbs_parser_marks_ibkr_self_transfer(tmp_path: Path):
    fixture = _write_dbs_fixture(
        tmp_path,
        "dbs_ibkr_transfer.csv",
        "19 Feb 2026,19 Feb 2026,ADV,Transfer to IBKR,IBG,Brokerage top up,REF,OTHR,Settled,SGD,1000,",
    )

    result = parse_dbs_transaction_history_csv(str(fixture))

    assert result.transactions[0]["type"] == "TRANSFER"


def test_dbs_parser_marks_paynow_transfer(tmp_path: Path):
    fixture = _write_dbs_fixture(
        tmp_path,
        "dbs_paynow_transfer.csv",
        "19 Feb 2026,19 Feb 2026,ADV,PayNow Transfer to friend,,Instant transfer,REF,OTHR,Settled,SGD,50,",
    )

    result = parse_dbs_transaction_history_csv(str(fixture))

    assert result.transactions[0]["type"] == "TRANSFER"


def test_dbs_parser_marks_self_credit_as_transfer(tmp_path: Path):
    fixture = _write_dbs_fixture(
        tmp_path,
        "dbs_self_credit.csv",
        "24 Apr 2026,24 Apr 2026,ADV,ICT self 20260424UOVBSGSGBRT7617851 OTHR,IBG,Payments,REF,OTHR,Settled,SGD,,20000",
    )

    result = parse_dbs_transaction_history_csv(str(fixture))

    assert result.transactions[0]["type"] == "TRANSFER"


def test_dbs_parser_giro_rent_debit_is_expense(tmp_path: Path):
    """Non-salary, non-self-transfer GIRO debit (e.g. rent to landlord) must be EXPENSE, not TRANSFER."""
    fixture = _write_dbs_fixture(
        tmp_path,
        "dbs_giro_rent.csv",
        "19 Feb 2026,19 Feb 2026,GR,GIRO RENT PAYMENT LANDLORD ABC,GIRO,Monthly rent,REF,OTHR,Settled,SGD,2500,",
    )

    result = parse_dbs_transaction_history_csv(str(fixture))

    assert result.transactions[0]["type"] == "EXPENSE"


def test_ibkr_parser_sections(tmp_path: Path):
    content = """Cash Transactions,Header,Date,Amount,Currency,Type,Description\nCash Transactions,Data,2026-02-02,10,USD,Dividend,Test\nTrades,Header,Date,Buy/Sell,Symbol,Net Cash,Currency\nTrades,Data,2026-02-03,BUY,AAPL,-1000,USD\nOpen Positions,Header,Symbol,Description,Asset Class,Quantity,Cost Price,Cost Basis,Currency\nOpen Positions,Data,AAPL,Apple Inc.,Stock,10,150,1500,USD\nForex Balances,Header,Asset Category,Description,Quantity\nForex Balances,Data,Forex,USD,500\n"""
    fixture = tmp_path / "ibkr.csv"
    fixture.write_text(content, encoding="utf-8")
    result = parse_ibkr_activity_csv(str(fixture), ",")
    assert result.section_counts["Cash Transactions"] == 2
    assert result.section_counts["Trades"] == 2
    assert len(result.transactions) == 2
    assert len(result.positions) == 2


def test_sharekhan_parser_html(tmp_path: Path):
    html = """<html><body>
    <table>
      <tr><th>SKSCRIPCODE</th><th>Stock Name</th><th>Current Qty</th><th>Investment Price</th><th>Holding Value</th><th>Market Value</th></tr>
      <tr><td>RELIANCE</td><td>Reliance</td><td>10</td><td>2500</td><td>25000</td><td>26000</td></tr>
    </table>
    </body></html>"""
    fixture = tmp_path / "sharekhan.xls"
    fixture.write_text(html, encoding="utf-8")
    result = parse_sharekhan_holdings_xls(str(fixture))
    assert result.section_counts["rows_parsed"] == 1
    assert result.positions[0]["symbol"] == "RELIANCE"
    assert result.parser_meta["sheet_name"].startswith("HTML_TABLE")


def test_dbs_vickers_parser_html(tmp_path: Path):
    html = """<html><body>
    <table>
      <tr><th>Symbol</th><th>Stock Name</th><th>Qty</th><th>Avg Price</th><th>Mkt Value</th></tr>
      <tr><td>S68</td><td>SGX</td><td>100</td><td>9.5</td><td>950</td></tr>
      <tr><td>S68</td><td>SGX</td><td>50</td><td>10</td><td>500</td></tr>
    </table>
    </body></html>"""
    fixture = tmp_path / "vickers.xls"
    fixture.write_text(html, encoding="utf-8")
    from app.ingestion.parsers.dbs_vickers_holdings_xls_v1 import parse_dbs_vickers_holdings_xls

    result = parse_dbs_vickers_holdings_xls(str(fixture))
    assert result.section_counts["rows_parsed"] == 2
    assert len(result.positions) == 1
    assert result.positions[0]["symbol"] == "S68"
    assert result.positions[0]["quantity"] == 150
    assert result.positions[0]["currency"] == "SGD"
    assert result.parser_meta["sheet_name"].startswith("HTML_TABLE")


def test_ocbc_parser_extracts_fixture_rows():
    fixture_name = "ocbc_TransactionHistory_20260313165630.csv"
    fixture = Path(__file__).resolve().parent / "fixtures" / fixture_name
    result = parse_ocbc_account_csv(str(fixture))

    assert len(result.transactions) == 20
    assert result.positions[0]["quantity"] == 25000.0
