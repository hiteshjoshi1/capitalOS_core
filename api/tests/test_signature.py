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


def test_signature_ocbc_flat_csv_fixture():
    fixture_name = "ocbc_TransactionHistory_20260313165630.csv"
    candidates = [
        Path("/app/data/fixtures") / fixture_name,
        Path(__file__).resolve().parents[2] / "data" / "fixtures" / fixture_name,
        Path(__file__).resolve().parents[1] / "data" / "fixtures" / fixture_name,
    ]
    fixture = next((candidate for candidate in candidates if candidate.exists()), candidates[0])
    sig, debug = compute_format_signature(str(fixture), platform_hint="OCBC")

    assert sig == "49291988f2110dd6431bf71a286f2192c98fba692608468006d052b33022423f"
    assert debug["file_kind"] == "flat_csv"
    assert debug["header"] == [
        "transaction date",
        "value date",
        "description",
        "withdrawals(sgd)",
        "deposits(sgd)",
    ]


def test_signature_citi_cc_headerless_stable(tmp_path: Path):
    csv_content_one = (
        "\"06/03/2026\",\"MERCHANT ONE SG\",\"-97.41\",\"\",\"'4147464004225540'\"\n"
        "\"05/03/2026\",\"PAYMENT - THANK YOU\",\"100.00\",\"\",\"'4147464004225540'\"\n"
    )
    csv_content_two = (
        "\"01/02/2026\",\"OTHER MERCHANT SG\",\"-12.30\",\"\",\"'9999888877776666'\"\n"
        "\"31/01/2026\",\"LATE CHARGE FEE\",\"-5.00\",\"\",\"'9999888877776666'\"\n"
    )
    fixture_one = tmp_path / "citi_1.csv"
    fixture_two = tmp_path / "citi_2.csv"
    fixture_one.write_text(csv_content_one, encoding="utf-8")
    fixture_two.write_text(csv_content_two, encoding="utf-8")

    sig_one, debug_one = compute_format_signature(str(fixture_one), platform_hint="CITI")
    sig_two, debug_two = compute_format_signature(str(fixture_two), platform_hint="CITI")
    assert sig_one == sig_two
    assert debug_one["file_kind"] == "citi_credit_card_csv"
    assert debug_two["file_kind"] == "citi_credit_card_csv"
    assert debug_one["column_count"] == 5


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
