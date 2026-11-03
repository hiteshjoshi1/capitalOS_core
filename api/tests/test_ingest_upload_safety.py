"""Upload storage naming and size cap (#132). Synthetic fixtures only."""

import io
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.ingestion.runner import stored_upload_name

DBS_CSV = (
    "Account Details For:,DBS\n"
    "Statement as at:,19 Feb 2026\n"
    "Currency:,SGD - Singapore Dollar\n"
    "Available Balance:,SGD 100.00\n"
    "Transaction Date,Value Date,Statement Code,Description,Supplementary Code,"
    "Supplementary Code Description,Client Reference,Additional Reference,Status,"
    "Currency,Debit Amount,Credit Amount\n"
    "19 Feb 2026,19 Feb 2026,GR,Salary,IBG,Payments,REF,OTHR,Settled,SGD,,50\n"
)


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch) -> Path:
    d = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(d))
    return d


@pytest.fixture
def account_id(db_engine) -> int:
    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        db.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country) VALUES "
                "(1320, 'Upload Safety Test', 'DBS', 'BANK', 'SGD', 'SG')"
            )
        )
        db.commit()
    finally:
        db.close()
    return 1320


def _job_count(db_engine) -> int:
    with db_engine.connect() as conn:
        return int(conn.execute(text("SELECT COUNT(*) FROM import_jobs")).scalar() or 0)


@pytest.mark.parametrize(
    ("original", "expected"),
    [
        ("statement.csv", "upload.csv"),
        ("Statement.CSV", "upload.csv"),
        ("holdings.XLS", "upload.xls"),
        ("holdings.xlsx", "upload.xlsx"),
        ("../../x.csv", "upload.csv"),
        ("/etc/cron.d/job.csv", "upload.csv"),
        ("..\\..\\win.xls", "upload.xls"),
        ("C:\\temp\\file.xlsx", "upload.xlsx"),
        ("script.sh", "upload"),
        ("noext", "upload"),
        ("..", "upload"),
        ("", "upload"),
    ],
)
def test_stored_upload_name_is_fixed(original: str, expected: str):
    assert stored_upload_name(original) == expected


@pytest.mark.parametrize("filename", ["../../x.csv", "/tmp/capitalos-upload-escape-test.csv"])
def test_traversal_or_absolute_filename_is_stored_inside_job_dir(
    client: TestClient, db_engine, data_dir: Path, account_id: int, filename: str
):
    resp = client.post(
        f"/ingest/upload?account_id={account_id}",
        files={"file": (filename, io.BytesIO(DBS_CSV.encode("utf-8")), "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["job_id"]

    with db_engine.connect() as conn:
        job = conn.execute(
            text("SELECT original_filename, stored_path FROM import_jobs WHERE id = :id"),
            {"id": job_id},
        ).mappings().one()
    assert job["original_filename"] == filename  # kept as metadata, unchanged
    raw_dir = os.path.realpath(data_dir / "raw" / str(job_id))
    assert os.path.realpath(job["stored_path"]) == os.path.join(raw_dir, "upload.csv")
    assert os.listdir(raw_dir) == ["upload.csv"]
    # Nothing landed at the requested location.
    assert not (data_dir / "x.csv").exists()
    assert not (data_dir.parent / "x.csv").exists()
    assert not os.path.exists("/tmp/capitalos-upload-escape-test.csv")

    # The stored copy still parses normally.
    resp2 = client.post(
        f"/ingest/jobs/{job_id}/register",
        json={"parser_key": "dbs_transaction_history_csv_v1"},
    )
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "IMPORTED"


def test_oversized_upload_rejected_with_413(
    client: TestClient, db_engine, data_dir: Path, account_id: int, monkeypatch
):
    # 1 KB cap; the 8 KB body is under the Content-Length allowance, so this
    # exercises the chunked per-file check.
    monkeypatch.setenv("INGEST_MAX_UPLOAD_MB", str(1 / 1024))
    before = _job_count(db_engine)
    resp = client.post(
        f"/ingest/upload?account_id={account_id}",
        files={"file": ("big.csv", io.BytesIO(b"a,b\n" * 2048), "text/csv")},
    )
    assert resp.status_code == 413
    assert "too large" in resp.json()["detail"]
    assert _job_count(db_engine) == before
    assert not (data_dir / "raw").exists()


def test_oversized_ibkr_upload_rejected_with_413(
    client: TestClient, db_engine, data_dir: Path, account_id: int, monkeypatch
):
    monkeypatch.setenv("INGEST_MAX_UPLOAD_MB", str(1 / 1024))
    resp = client.post(
        f"/ingest/ibkr?account_id={account_id}",
        files={"file": ("big.csv", io.BytesIO(b"x" * 8192), "text/csv")},
    )
    assert resp.status_code == 413


def test_oversized_content_length_rejected_before_body_is_read(
    client: TestClient, data_dir: Path, monkeypatch
):
    monkeypatch.setenv("INGEST_MAX_UPLOAD_MB", str(1 / 1024))
    # Unknown account: the handler would answer 404, so a 413 shows the
    # Content-Length check refused the request before the route ran.
    resp = client.post(
        "/ingest/upload?account_id=987654",
        files={"file": ("big.csv", io.BytesIO(b"x" * (200 * 1024)), "text/csv")},
    )
    assert resp.status_code == 413
    assert "too large" in resp.json()["detail"]


def test_upload_under_default_cap_is_accepted(client: TestClient, data_dir: Path, account_id: int, monkeypatch):
    monkeypatch.delenv("INGEST_MAX_UPLOAD_MB", raising=False)
    resp = client.post(
        f"/ingest/upload?account_id={account_id}",
        files={"file": ("dbs.csv", io.BytesIO(DBS_CSV.encode("utf-8")), "text/csv")},
    )
    assert resp.status_code == 200
