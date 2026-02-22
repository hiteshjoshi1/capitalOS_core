import os
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

from app.ingestion.signature import compute_format_signature
from app.ingestion.registry import register_signature


def test_ibkr_ingest_creates_transactions(client: TestClient, db_engine, tmp_path):
    data_dir = os.getenv("DATA_DIR", "/tmp/capitalos_test_data")
    os.makedirs(data_dir, exist_ok=True)

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        db.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country) VALUES "
                "(100, 'Test IBKR', 'IBKR', 'BROKER', 'USD', 'US')"
            )
        )
        db.commit()

        csv_content = """Cash Transactions,Header,Date,Amount,Currency,Type,Description
Cash Transactions,Data,2026-02-02,10,USD,Dividend,Test
"""
        fixture = tmp_path / "ibkr.csv"
        fixture.write_text(csv_content, encoding="utf-8")
        fixture_path = str(fixture)
        signature, _ = compute_format_signature(fixture_path, platform_hint="IBKR")
        register_signature(db, signature, "ibkr_activity_csv_v1", 1)
    finally:
        db.close()

    with open(fixture_path, "rb") as f:
        resp = client.post(
            "/ingest/ibkr?account_id=100",
            files={"file": ("ibkr_activity_sample.csv", f, "text/csv")},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "IMPORTED"
    assert data["counts"]["transactions_inserted"] > 0

    # Re-upload should be idempotent
    with open(fixture_path, "rb") as f:
        resp2 = client.post(
            "/ingest/ibkr?account_id=100",
            files={"file": ("ibkr_activity_sample.csv", f, "text/csv")},
        )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["counts"]["duplicates_skipped"] >= data["counts"]["transactions_inserted"]


def test_ibkr_positions_parsing(tmp_path):
    csv_content = """Open Positions,Header,Symbol,Description,Asset Class,Quantity,Cost Price,Cost Basis,Currency
Open Positions,Data,AAPL,Apple Inc.,Stock,10,150,1500,USD
"""
    fixture = tmp_path / "ibkr_positions.csv"
    fixture.write_text(csv_content, encoding="utf-8")

    from app.ingestion.signature import compute_format_signature
    from app.ingestion.parsers.ibkr_activity_csv_v1 import parse_ibkr_activity_csv

    sig, debug = compute_format_signature(str(fixture), platform_hint="IBKR")
    delimiter = debug["delimiter"]
    txs, positions, sections = parse_ibkr_activity_csv(str(fixture), delimiter)
    assert sig
    assert sections.get("Open Positions") == 2
    assert len(positions) == 1
    pos = positions[0]
    assert pos["symbol"] == "AAPL"
    assert pos["asset_class"] == "STOCK"
    assert pos["quantity"] == 10.0
    assert pos["cost_basis_base"] == 1500.0
