from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.ingestion.registry import register_signature
from app.ingestion.signature import compute_format_signature


def test_ingest_upload_and_register(client: TestClient, db_engine, tmp_path: Path):
    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        db.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country) VALUES "
                "(400, 'DBS Test', 'DBS', 'BANK', 'SGD', 'SG')"
            )
        )
        db.commit()
    finally:
        db.close()

    csv_content = """Account Details For:,DBS\nStatement as at:,19 Feb 2026\nCurrency:,SGD - Singapore Dollar\nAvailable Balance:,SGD 100.00\nTransaction Date,Value Date,Statement Code,Description,Supplementary Code,Supplementary Code Description,Client Reference,Additional Reference,Status,Currency,Debit Amount,Credit Amount\n19 Feb 2026,19 Feb 2026,GR,Salary,IBG,Payments,REF,OTHR,Settled,SGD,,50\n"""
    fixture = tmp_path / "dbs.csv"
    fixture.write_text(csv_content, encoding="utf-8")

    with open(fixture, "rb") as f:
        resp = client.post(
            "/ingest/upload?account_id=400",
            files={"file": ("dbs.csv", f, "text/csv")},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "NEEDS_MAPPING"
    job_id = data["job_id"]

    resp2 = client.post(
        f"/ingest/jobs/{job_id}/register",
        json={"parser_key": "dbs_transaction_history_csv_v1"},
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["status"] == "IMPORTED"


def test_ingest_upload_prefers_account_platform_over_generic_platform_code(
    client: TestClient, db_engine, tmp_path: Path
):
    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        db.execute(
            text(
                "INSERT INTO platforms (id, code, name, platform_type, country) VALUES "
                "(901, 'DBS', 'DBS Bank', 'BANK', 'SG')"
            )
        )
        db.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country, platform_id) VALUES "
                "(902, 'DBS Vickers Test', 'DBS_VICKERS', 'BROKER', 'SGD', 'SG', 901)"
            )
        )
        db.commit()
    finally:
        db.close()

    html = """<html><body>
    <table>
      <tr><th>Symbol</th><th>Stock Name</th><th>Qty</th><th>Avg Price</th><th>Mkt Value</th></tr>
      <tr><td>S68</td><td>SGX</td><td>100</td><td>9.5</td><td>950</td></tr>
    </table>
    </body></html>"""
    fixture = tmp_path / "dbs_vickers_fixture.xls"
    fixture.write_text(html, encoding="utf-8")

    sig, _ = compute_format_signature(str(fixture), platform_hint="DBS_VICKERS")
    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        register_signature(db, sig, "dbs_vickers_holdings_xls_v1", 1)
    finally:
        db.close()

    with open(fixture, "rb") as f:
        resp = client.post(
            "/ingest/upload?account_id=902",
            files={"file": ("dbs_vickers_2026_02_19.xls", f, "application/vnd.ms-excel")},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "IMPORTED"
    assert data["platform"] == "DBS_VICKERS"
    assert data["parser_key"] == "dbs_vickers_holdings_xls_v1"
    assert data["counts"]["positions_inserted"] > 0
