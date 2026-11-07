from __future__ import annotations

import logging
import os
import tempfile
from datetime import date, timedelta
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.clock import app_today
from app.auth_context import CurrentUser, account_scope_sql, require_current_user
from app.db.session import get_db
from app.fx_backfill import backfill_in_background
from app.ingestion.runner import PARSER_REGISTRY, create_import_job, run_ingestion
from app.ingestion.registry import register_signature
from app.ingestion.account_checks import account_type_of, check_parser_account_type
from app.ingestion.undo import RemovalRefused, remove_import_job
from pydantic import BaseModel
from app.models.import_job import ImportJob
from app.portfolio.ibkr_flex import is_ibkr_flex_cutover_active

logger = logging.getLogger("capitalos.ingest")

router = APIRouter(prefix="/ingest", tags=["ingest"], dependencies=[Depends(require_current_user)])


class RegisterPayload(BaseModel):
    parser_key: str
    # The upload's as-of date, re-sent when a NEEDS_MAPPING upload is approved (#141).
    as_of: date | None = None
    # Import even though the file names a different account than the one linked (#180).
    allow_account_mismatch: bool = False


def _raise_if_refused(report: dict) -> dict:
    """A refused upload (#180) is a 409 whose detail says why; nothing was written.

    ``detail`` carries ``code`` (account_type_mismatch | statement_account_mismatch),
    ``message`` and ``job_id``; a statement mismatch also names ``override_field``,
    the form field that uploads it anyway.
    """
    if report.get("status") != "REJECTED":
        return report
    refusal = dict(report.get("refusal") or {})
    refusal.setdefault("message", report.get("error_message") or "Upload refused")
    refusal["job_id"] = report.get("job_id")
    raise HTTPException(status_code=409, detail=refusal)


def _data_dir() -> str:
    return os.getenv("DATA_DIR", os.path.join(os.getcwd(), "data"))

DEFAULT_MAX_UPLOAD_MB = 25
_UPLOAD_CHUNK_BYTES = 1024 * 1024


def max_upload_bytes() -> int:
    """Upload size cap in bytes, from ``INGEST_MAX_UPLOAD_MB`` (default 25)."""
    raw = os.getenv("INGEST_MAX_UPLOAD_MB", "").strip()
    try:
        mb = float(raw) if raw else DEFAULT_MAX_UPLOAD_MB
    except ValueError:
        mb = DEFAULT_MAX_UPLOAD_MB
    if mb <= 0:
        mb = DEFAULT_MAX_UPLOAD_MB
    return int(mb * 1024 * 1024)


def _too_large(limit: int) -> HTTPException:
    return HTTPException(
        status_code=413,
        detail=f"File is too large. The upload limit is {limit // (1024 * 1024)} MB (INGEST_MAX_UPLOAD_MB).",
    )


def _spool_upload(file: UploadFile) -> str:
    """Copy the upload to a temp file in chunks, enforcing the size cap.

    Returns the temp file path; raises 413 (and removes the partial file) when the
    upload is over the limit. The body is never held in memory as a whole.
    """
    limit = max_upload_bytes()
    size = getattr(file, "size", None)
    if size is not None and size > limit:
        raise _too_large(limit)
    total = 0
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp_path = tmp.name
        try:
            while True:
                chunk = file.file.read(_UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise _too_large(limit)
                tmp.write(chunk)
        except BaseException:
            tmp.close()
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise
    return tmp_path


# Allowance for multipart framing (boundaries, part headers) on top of the file itself.
_MULTIPART_OVERHEAD_BYTES = 64 * 1024


class UploadSizeLimitMiddleware:
    """Refuse ``POST /ingest/...`` bodies whose Content-Length is over the cap.

    Runs before the multipart body is read, so an oversized upload is not received
    at all. Bodies without a Content-Length (chunked) fall through to the
    per-file check in ``_spool_upload``.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] == "http"
            and scope.get("method") == "POST"
            and str(scope.get("path", "")).startswith("/ingest/")
        ):
            limit = max_upload_bytes()
            for key, value in scope.get("headers", []):
                if key.lower() == b"content-length":
                    try:
                        length = int(value)
                    except ValueError:
                        break
                    if length > limit + _MULTIPART_OVERHEAD_BYTES:
                        from fastapi.responses import JSONResponse

                        response = JSONResponse(status_code=413, content={"detail": _too_large(limit).detail})
                        await response(scope, receive, send)
                        return
                    break
        await self.app(scope, receive, send)


def _require_account_platform(db: Session, account_id: int, current_user_id: int) -> str:
    from sqlalchemy import text

    row = db.execute(
        text(
            """
            SELECT COALESCE(NULLIF(TRIM(a.platform), ''), p.code)
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


def _reject_ibkr_manual_upload_after_flex_cutover(db: Session, account_id: int, platform: str) -> None:
    if str(platform or "").upper() != "IBKR":
        return
    if is_ibkr_flex_cutover_active(db, account_id, on_date=app_today()):
        raise HTTPException(
            status_code=409,
            detail="Manual IBKR uploads are disabled after IBKR Flex cutover. Use /portfolio/ibkr-flex/import-now.",
        )


@router.post("/ibkr")
def ingest_ibkr(
    account_id: int = Query(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    platform = _require_account_platform(db, account_id, current_user.id)
    _reject_ibkr_manual_upload_after_flex_cutover(db, account_id, platform)

    data_dir = _data_dir()
    os.makedirs(data_dir, exist_ok=True)

    tmp_path = _spool_upload(file)

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
        if report.get("status") == "IMPORTED":
            _backfill_fx_after_import(db, current_user.id)
        return _raise_if_refused(report)
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def _check_as_of(as_of: date | None) -> None:
    # One day of slack: the browser's local "today" can be ahead of the app timezone.
    if as_of is not None and as_of > app_today() + timedelta(days=1):
        raise HTTPException(status_code=400, detail="as_of can't be in the future")


@router.post("/upload")
def ingest_upload(
    account_id: int = Query(...),
    file: UploadFile = File(...),
    as_of: date | None = Form(
        None,
        description="The statement's as-of date (YYYY-MM-DD), used when the file states none of its own (#141).",
    ),
    allow_account_mismatch: bool = Form(
        False,
        description="Import even though the file names a different account than the one this account's "
        "statements name (#180). The account-type check has no override.",
    ),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")
    _check_as_of(as_of)

    platform = _require_account_platform(db, account_id, current_user.id)
    _reject_ibkr_manual_upload_after_flex_cutover(db, account_id, platform)

    data_dir = _data_dir()
    os.makedirs(data_dir, exist_ok=True)

    tmp_path = _spool_upload(file)

    try:
        job = create_import_job(
            db=db,
            account_id=account_id,
            platform=platform,
            original_filename=file.filename,
            upload_path=tmp_path,
            data_dir=data_dir,
        )
        report = run_ingestion(
            db=db,
            job_id=job.id,
            data_dir=data_dir,
            as_of=as_of,
            allow_account_mismatch=allow_account_mismatch,
        )
        if report.get("status") == "IMPORTED":
            _backfill_account_categories(db, account_id)
            _backfill_fx_after_import(db, current_user.id)
        return _raise_if_refused(report)
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def _backfill_fx_after_import(db: Session, user_id: int) -> None:
    """Past FX rates for the new data's span (#290), in the background; never fails the upload."""
    try:
        row = db.execute(
            text("SELECT base_currency FROM user_preferences WHERE user_id = :uid"), {"uid": user_id}
        ).first()
        base = str(row[0]) if row and row[0] else "SGD"
        backfill_in_background(user_id, base)
    except Exception as exc:  # noqa: BLE001
        logger.warning("fx_backfill_start_failed", extra={"event": "fx_backfill_start_failed", "error_class": exc.__class__.__name__})


def _backfill_account_categories(db: Session, account_id: int) -> None:
    """Run rule-based category backfill for all transactions in an account.

    Called automatically after a successful ingest so that seed rules resolve
    merchant categories without requiring a separate manual backfill step.
    """
    from sqlalchemy import text as _text
    from app.category_engine import apply_rules

    tx_rows = db.execute(
        _text("SELECT id FROM transactions WHERE account_id = :account_id"),
        {"account_id": account_id},
    ).fetchall()
    tx_ids = [int(row[0]) for row in tx_rows]
    if tx_ids:
        apply_rules(db, tx_ids)


@router.get("/jobs")
def list_jobs(
    db: Session = Depends(get_db),
    limit: int = Query(25, ge=1, le=100),
    current_user: CurrentUser = Depends(require_current_user),
):
    rows = db.execute(
        text(
            """
            SELECT ij.id, ij.status, ij.platform, ij.account_id, ij.original_filename, ij.created_at,
                   ij.error_message, ij.removed_at, (ij.undo_json IS NOT NULL) AS has_undo_log
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
            "created_at": _iso(r["created_at"]),
            # #180: why it was refused or failed, when it was removed, and
            # whether "Remove this import" can undo it.
            "error_message": r["error_message"],
            "removed_at": _iso(r["removed_at"]),
            "removable": r["status"] == "IMPORTED" and bool(r["has_undo_log"]),
        }
        for r in rows
    ]


def _iso(value) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


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
    # The registry is shared by every user, so only an admin may write it (#153).
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Only an admin can register a file format")
    parser_key = (payload.parser_key or "").strip()
    if parser_key not in PARSER_REGISTRY:
        raise HTTPException(status_code=400, detail=f"Unknown parser_key: {parser_key!r}")
    job = db.query(ImportJob).filter(ImportJob.id == job_id).one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    _require_account_platform(db, int(job.account_id), current_user.id)
    if job.status in ("IMPORTED", "REMOVED"):
        raise HTTPException(status_code=409, detail=f"Job is already {job.status}; upload the file again instead")
    if not job.format_signature:
        raise HTTPException(status_code=400, detail="Job has no format_signature")
    _check_as_of(payload.as_of)
    # Refuse before the shared registry is written: a mapping registered from the
    # wrong account would misroute every later upload of this format (#180).
    wrong_type = check_parser_account_type(parser_key, account_type_of(db, int(job.account_id)))
    if wrong_type is not None:
        raise HTTPException(status_code=409, detail={**wrong_type.as_dict(), "job_id": int(job.id)})
    # An admin registering a signature that is already mapped corrects the mapping.
    register_signature(db, job.format_signature, parser_key, 1, replace=True)
    report = run_ingestion(
        db=db,
        job_id=job.id,
        data_dir=_data_dir(),
        as_of=payload.as_of,
        allow_account_mismatch=payload.allow_account_mismatch,
    )
    return _raise_if_refused(report)


@router.post("/jobs/{job_id}/remove")
def remove_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    """Remove an upload's rows (#180): its transactions, balance snapshots and
    holdings, putting back what it replaced, and mark History dirty from the
    earliest affected date. The job row stays, with status REMOVED.

    Only the owner of the job's account can remove it (404 otherwise). 409 when it
    can't be removed (not imported, imported before removal existed, or a later
    upload replaced its rows); nothing is changed then.
    """
    job = db.query(ImportJob).filter(ImportJob.id == job_id).one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    _require_account_platform(db, int(job.account_id), current_user.id)
    try:
        return remove_import_job(db, job)
    except RemovalRefused as refused:
        db.rollback()
        raise HTTPException(status_code=refused.status_code, detail=refused.message) from refused
