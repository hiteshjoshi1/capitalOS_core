from __future__ import annotations

import os
import tempfile
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_context import CurrentUser, account_scope_sql, require_current_user
from app.db.session import get_db
from app.ingestion.runner import create_import_job, run_ingestion
from app.ingestion.registry import register_signature
from pydantic import BaseModel
from app.models.import_job import ImportJob

router = APIRouter(prefix="/ingest", tags=["ingest"], dependencies=[Depends(require_current_user)])


class RegisterPayload(BaseModel):
    parser_key: str


def _data_dir() -> str:
    return os.getenv("DATA_DIR", os.path.join(os.getcwd(), "data"))

def _require_account_platform(db: Session, account_id: int, current_user_id: int) -> str:
    from sqlalchemy import text

    row = db.execute(
        text(
            """
            SELECT COALESCE(p.code, a.platform)
            FROM accounts AS a
            LEFT JOIN platforms AS p ON p.id = a.platform_id
            WHERE a.id = :account_id
              AND """
            + account_scope_sql("a")
            + """
            """
        ),
        {"account_id": account_id, "current_user_id": current_user_id},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Account not found")
    return row[0] or "UNKNOWN"


@router.post("/ibkr")
def ingest_ibkr(
    account_id: int = Query(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    _require_account_platform(db, account_id, current_user.id)

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
def ingest_upload(
    account_id: int = Query(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    platform = _require_account_platform(db, account_id, current_user.id)

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
def list_jobs(
    db: Session = Depends(get_db),
    limit: int = Query(25, ge=1, le=100),
    current_user: CurrentUser = Depends(require_current_user),
):
    rows = db.execute(
        text(
            """
            SELECT ij.id, ij.status, ij.platform, ij.account_id, ij.original_filename, ij.created_at
            FROM import_jobs ij
            JOIN accounts a ON a.id = ij.account_id
            WHERE """
            + account_scope_sql("a")
            + """
            ORDER BY ij.created_at DESC
            LIMIT :limit
            """
        ),
        {"current_user_id": current_user.id, "limit": limit},
    ).mappings().all()
    return [
        {
            "id": int(r["id"]),
            "status": r["status"],
            "platform": r["platform"],
            "account_id": int(r["account_id"]),
            "original_filename": r["original_filename"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


@router.get("/jobs/{job_id}")
def get_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    job = db.execute(
        text(
            """
            SELECT ij.*
            FROM import_jobs ij
            JOIN accounts a ON a.id = ij.account_id
            WHERE ij.id = :job_id
              AND """
            + account_scope_sql("a")
            + """
            LIMIT 1
            """
        ),
        {"job_id": job_id, "current_user_id": current_user.id},
    ).mappings().one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    report = None
    report_path = job.get("report_path")
    if report_path and os.path.exists(report_path):
        with open(report_path, "r", encoding="utf-8") as f:
            report = f.read()
            try:
                import json
                report = json.loads(report)
            except Exception:
                pass
    return {
        "job": {
            "id": int(job["id"]),
            "status": job["status"],
            "platform": job["platform"],
            "account_id": int(job["account_id"]),
            "original_filename": job["original_filename"],
            "stored_path": job["stored_path"],
            "file_sha256": job["file_sha256"],
            "format_signature": job["format_signature"],
            "parser_key": job["parser_key"],
            "report_path": job["report_path"],
            "error_message": job["error_message"],
            "created_at": job["created_at"].isoformat() if job["created_at"] else None,
            "updated_at": job["updated_at"].isoformat() if job["updated_at"] else None,
        },
        "report": report,
    }


@router.post("/jobs/{job_id}/register")
def register_job_signature(
    job_id: int,
    payload: RegisterPayload,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    job = db.query(ImportJob).filter(ImportJob.id == job_id).one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    _require_account_platform(db, int(job.account_id), current_user.id)
    if not job.format_signature:
        raise HTTPException(status_code=400, detail="Job has no format_signature")
    register_signature(db, job.format_signature, payload.parser_key, 1)
    report = run_ingestion(db=db, job_id=job.id, data_dir=_data_dir())
    return report
