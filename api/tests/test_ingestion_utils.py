import os
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.ingestion.registry import register_signature, lookup_parser_key
from app.ingestion.runner import create_import_job, run_ingestion
from app.ingestion.validators import validate_transactions
from app.ingestion.report import write_report


def test_registry_roundtrip(db_engine):
    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        register_signature(db, "sig-123", "parser_key", 1)
        assert lookup_parser_key(db, "sig-123") == "parser_key"
    finally:
        db.close()


def test_validate_transactions_warnings():
    warnings = validate_transactions([{"amount": None, "currency": "", "type": ""}])
    assert "Missing amount" in warnings[0]
    assert "Missing currency" in warnings[1]
    assert "Missing type" in warnings[2]


def test_write_report(tmp_path: Path):
    report_path = tmp_path / "report.json"
    write_report(str(report_path), {"ok": True})
    assert report_path.exists()
    assert report_path.read_text(encoding="utf-8").strip() != ""


def test_run_ingestion_needs_mapping(tmp_path: Path, db_engine):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    sample = tmp_path / "sample.csv"
    sample.write_text("Transaction Date,Value Date,Statement Code\n", encoding="utf-8")

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        db.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country) VALUES "
                "(300, 'Test DBS', 'DBS', 'BANK', 'SGD', 'SG')"
            )
        )
        db.commit()
        job = create_import_job(
            db=db,
            account_id=300,
            platform="DBS",
            original_filename="sample.csv",
            upload_path=str(sample),
            data_dir=str(data_dir),
        )
        report = run_ingestion(db=db, job_id=job.id, data_dir=str(data_dir))
        assert report["status"] == "NEEDS_MAPPING"
    finally:
        db.close()
