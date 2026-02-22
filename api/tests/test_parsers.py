from pathlib import Path

from app.ingestion.parsers.dbs_transaction_history_csv_v1 import parse_dbs_transaction_history_csv
from app.ingestion.parsers.ibkr_activity_csv_v1 import parse_ibkr_activity_csv
from app.ingestion.parsers.sharekhan_holdings_xls_v1 import parse_sharekhan_holdings_xls


def test_dbs_parser_extracts_cash_and_transactions(tmp_path: Path):
    content = """Account Details For:,DBS Multiplier\nStatement as at:,19 Feb 2026\nCurrency:,SGD - Singapore Dollar\nAvailable Balance:,SGD 1000.00\nLedger Balance:,SGD 900.00\nTransaction Date,Value Date,Statement Code,Description,Supplementary Code,Supplementary Code Description,Client Reference,Additional Reference,Status,Currency,Debit Amount,Credit Amount\n19 Feb 2026,19 Feb 2026,GR,Salary,IBG,Payments,REF,OTHR,Settled,SGD,,500\n"""
    fixture = tmp_path / "dbs.csv"
    fixture.write_text(content, encoding="utf-8")
    txs, positions, _ = parse_dbs_transaction_history_csv(str(fixture))
    assert len(txs) == 1
    assert txs[0]["type"] == "INCOME"
    assert positions
    assert positions[0]["asset_class"] == "CASH"
    assert positions[0]["currency"] == "SGD"


def test_ibkr_parser_sections(tmp_path: Path):
    content = """Cash Transactions,Header,Date,Amount,Currency,Type,Description\nCash Transactions,Data,2026-02-02,10,USD,Dividend,Test\nTrades,Header,Date,Buy/Sell,Symbol,Net Cash,Currency\nTrades,Data,2026-02-03,BUY,AAPL,-1000,USD\nOpen Positions,Header,Symbol,Description,Asset Class,Quantity,Cost Price,Cost Basis,Currency\nOpen Positions,Data,AAPL,Apple Inc.,Stock,10,150,1500,USD\nForex Balances,Header,Asset Category,Description,Quantity\nForex Balances,Data,Forex,USD,500\n"""
    fixture = tmp_path / "ibkr.csv"
    fixture.write_text(content, encoding="utf-8")
    txs, positions, sections = parse_ibkr_activity_csv(str(fixture), ",")
    assert sections["Cash Transactions"] == 2
    assert sections["Trades"] == 2
    assert len(txs) == 2
    assert len(positions) == 2


def test_sharekhan_parser_html(tmp_path: Path):
    html = """<html><body>
    <table>
      <tr><th>SKSCRIPCODE</th><th>Stock Name</th><th>Current Qty</th><th>Investment Price</th><th>Holding Value</th><th>Market Value</th></tr>
      <tr><td>RELIANCE</td><td>Reliance</td><td>10</td><td>2500</td><td>25000</td><td>26000</td></tr>
    </table>
    </body></html>"""
    fixture = tmp_path / "sharekhan.xls"
    fixture.write_text(html, encoding="utf-8")
    _, positions, counts, meta = parse_sharekhan_holdings_xls(str(fixture))
    assert counts["rows_parsed"] == 1
    assert positions[0]["symbol"] == "RELIANCE"
    assert meta["sheet_name"].startswith("HTML_TABLE")
