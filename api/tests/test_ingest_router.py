from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker


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
