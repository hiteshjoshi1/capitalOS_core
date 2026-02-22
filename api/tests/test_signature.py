from pathlib import Path

from app.ingestion.signature import compute_format_signature


def test_signature_ibkr_csv(tmp_path: Path):
    csv_content = """Statement,Header,Date,Value
Statement,Data,2026-02-01,100
Cash Transactions,Header,Date,Amount,Currency,Type,Description
Cash Transactions,Data,2026-02-02,10,USD,Dividend,Test
"""
    fixture = tmp_path / "ibkr.csv"
    fixture.write_text(csv_content, encoding="utf-8")
    sig, debug = compute_format_signature(str(fixture), platform_hint="IBKR")
    assert sig
    assert debug["file_kind"] == "ibkr_activity_csv"
    assert "cash transactions" in debug["sections"]


def test_signature_flat_csv(tmp_path: Path):
    csv_content = "Transaction Date,Value Date,Statement Code,Description\n2026-02-01,2026-02-01,ADV,Test"
    fixture = tmp_path / "dbs.csv"
    fixture.write_text(csv_content, encoding="utf-8")
    sig, debug = compute_format_signature(str(fixture), platform_hint="DBS")
    assert sig
    assert debug["file_kind"] == "flat_csv"
    assert "transaction date" in debug["header"][0]


def test_signature_html_table(tmp_path: Path):
    html = """<html><body>
    <table>
      <tr><th>Scrip Name</th><th>Available Qty</th><th>Holding Value</th></tr>
      <tr><td>RELIANCE</td><td>10</td><td>25000</td></tr>
    </table>
    </body></html>"""
    fixture = tmp_path / "sharekhan.xls"
    fixture.write_text(html, encoding="utf-8")
    sig, debug = compute_format_signature(str(fixture), platform_hint="SHAREKHAN")
    assert sig
    assert debug["file_kind"] == "html_table"
    assert any("available" in h for h in debug["header"])
