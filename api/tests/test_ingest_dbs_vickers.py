import os

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.ingestion.signature import compute_format_signature
from app.ingestion.registry import register_signature


def test_dbs_vickers_holdings_ingest(client: TestClient, db_engine):
    data_dir = os.getenv("DATA_DIR", "/tmp/capitalos_test_data")
    os.makedirs(data_dir, exist_ok=True)

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        db.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country) VALUES "
                "(201, 'Test DBS Vickers', 'DBS_VICKERS', 'BROKER', 'SGD', 'SG')"
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
    fixture = os.path.join(data_dir, "dbs_vickers_fixture.xls")
    with open(fixture, "w", encoding="utf-8") as f:
        f.write(html)

    sig, _ = compute_format_signature(str(fixture), platform_hint="DBS_VICKERS")
    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        register_signature(db, sig, "dbs_vickers_holdings_xls_v1", 1)
    finally:
        db.close()

    with open(fixture, "rb") as f:
        resp = client.post(
            "/ingest/upload?account_id=201",
            files={"file": ("dbs_vickers_2026_02_19.xls", f, "application/vnd.ms-excel")},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "IMPORTED"
    assert data["counts"]["positions_inserted"] > 0

    # Re-upload should upsert (no duplicate rows)
    with open(fixture, "rb") as f:
        resp2 = client.post(
            "/ingest/upload?account_id=201",
            files={"file": ("dbs_vickers_2026_02_19.xls", f, "application/vnd.ms-excel")},
        )
    assert resp2.status_code == 200
    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        count = db.execute(text("SELECT COUNT(*) FROM positions WHERE account_id = 201")).scalar()
    finally:
        db.close()
    assert count > 0
