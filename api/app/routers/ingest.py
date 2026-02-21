from __future__ import annotations

import os
import tempfile
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.ingestion.runner import create_import_job, run_ingestion
from app.ingestion.registry import register_signature
from pydantic import BaseModel
from app.models.import_job import ImportJob

router = APIRouter(prefix="/ingest", tags=["ingest"])


class RegisterPayload(BaseModel):
    parser_key: str


def _data_dir() -> str:
    return os.getenv("DATA_DIR", os.path.join(os.getcwd(), "data"))

def _require_account_platform(db: Session, account_id: int) -> str:
    from sqlalchemy import text

    row = db.execute(
        text("SELECT platform FROM accounts WHERE id = :account_id"),
        {"account_id": account_id},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Account not found")
    return row[0] or "UNKNOWN"


@router.post("/ibkr")
def ingest_ibkr(account_id: int = Query(...), file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    _require_account_platform(db, account_id)

    data_dir = _data_dir()
    os.makedirs(data_dir, exist_ok=True)

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(file.file.read())
        tmp_path = tmp.name

    try:
        job = create_import_job(
            db=db,
            account_id=account_id,
            platform="IBKR",
            original_filename=file.filename,
            upload_path=tmp_path,
            data_dir=data_dir,
        )
        report = run_ingestion(db=db, job_id=job.id, data_dir=data_dir)
        return report
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


@router.post("/upload")
def ingest_upload(account_id: int = Query(...), file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    platform = _require_account_platform(db, account_id)

    data_dir = _data_dir()
    os.makedirs(data_dir, exist_ok=True)

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(file.file.read())
        tmp_path = tmp.name

    try:
        job = create_import_job(
            db=db,
            account_id=account_id,
            platform=platform,
            original_filename=file.filename,
            upload_path=tmp_path,
            data_dir=data_dir,
        )
        report = run_ingestion(db=db, job_id=job.id, data_dir=data_dir)
        return report
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


@router.get("/jobs")
def list_jobs(db: Session = Depends(get_db), limit: int = Query(25, ge=1, le=100)):
    rows = (
        db.query(ImportJob)
        .order_by(ImportJob.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "status": r.status,
            "platform": r.platform,
            "account_id": r.account_id,
            "original_filename": r.original_filename,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.get("/jobs/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(ImportJob).filter(ImportJob.id == job_id).one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    report = None
    if job.report_path and os.path.exists(job.report_path):
        with open(job.report_path, "r", encoding="utf-8") as f:
            report = f.read()
            try:
                import json
                report = json.loads(report)
            except Exception:
                pass
    return {
        "job": {
            "id": job.id,
            "status": job.status,
            "platform": job.platform,
            "account_id": job.account_id,
            "original_filename": job.original_filename,
            "stored_path": job.stored_path,
            "file_sha256": job.file_sha256,
            "format_signature": job.format_signature,
            "parser_key": job.parser_key,
            "report_path": job.report_path,
            "error_message": job.error_message,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        },
        "report": report,
    }


@router.post("/jobs/{job_id}/register")
def register_job_signature(job_id: int, payload: RegisterPayload, db: Session = Depends(get_db)):
    job = db.query(ImportJob).filter(ImportJob.id == job_id).one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.format_signature:
        raise HTTPException(status_code=400, detail="Job has no format_signature")
    register_signature(db, job.format_signature, payload.parser_key, 1)
    report = run_ingestion(db=db, job_id=job.id, data_dir=_data_dir())
    return report
