import os
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from fastapi.testclient import TestClient

from app.ingestion.signature import compute_format_signature
from app.ingestion.registry import register_signature


def test_sharekhan_holdings_ingest(client: TestClient, db_engine, tmp_path):
    data_dir = os.getenv("DATA_DIR", "/tmp/capitalos_test_data")
    os.makedirs(data_dir, exist_ok=True)

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        db.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country) VALUES "
                "(200, 'Test Sharekhan', 'SHAREKHAN', 'BROKER', 'INR', 'IN')"
            )
        )
        db.commit()
    finally:
        db.close()

    html = """<html><body>
    <table>
      <tr><th>Scrip Name</th><th>Available Qty</th><th>Hold Price</th><th>Hold Value</th><th>Market Price</th><th>Market Value</th></tr>
      <tr><td>RELIANCE</td><td>10</td><td>2500</td><td>25000</td><td>2600</td><td>26000</td></tr>
    </table>
    </body></html>"""
    fixture = tmp_path / "sharekhan_holdings.xls"
    fixture.write_text(html, encoding="utf-8")

    sig, _ = compute_format_signature(str(fixture), platform_hint="SHAREKHAN")
    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        register_signature(db, sig, "sharekhan_holdings_xls_v1", 1)
    finally:
        db.close()

    with open(fixture, "rb") as f:
        resp = client.post(
            "/ingest/upload?account_id=200",
            files={"file": ("sharekhan_holdings.xls", f, "application/vnd.ms-excel")},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "IMPORTED"
    assert data["counts"]["positions_inserted"] == 1

    # Re-upload should upsert (no duplicate rows)
    with open(fixture, "rb") as f:
        resp2 = client.post(
            "/ingest/upload?account_id=200",
            files={"file": ("sharekhan_holdings.xls", f, "application/vnd.ms-excel")},
        )
    assert resp2.status_code == 200
    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        count = db.execute(text("SELECT COUNT(*) FROM positions WHERE account_id = 200")).scalar()
    finally:
        db.close()
    assert count == 1
