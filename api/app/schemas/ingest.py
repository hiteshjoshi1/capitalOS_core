"""Response models for the ingest GET routes (#361): the same JSON as before, minus the
server file path ``stored_path`` (D-99)."""

from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel


class ImportJobListItem(BaseModel):
    """GET /ingest/jobs: one upload, newest first."""

    id: int
    status: str
    platform: Optional[str] = None
    account_id: int
    original_filename: Optional[str] = None
    created_at: Optional[str] = None
    error_message: Optional[str] = None
    removed_at: Optional[str] = None
    removable: bool


class ImportJobDetail(BaseModel):
    id: int
    status: str
    platform: Optional[str] = None
    account_id: int
    original_filename: Optional[str] = None
    file_sha256: Optional[str] = None
    format_signature: Optional[str] = None
    parser_key: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ImportJobResponse(BaseModel):
    """GET /ingest/jobs/{job_id}: the job and its import report (the report file's JSON, or its
    text when it isn't JSON; null when there is none)."""

    job: ImportJobDetail
    report: Any = None


ImportJobList = List[ImportJobListItem]


class UploadDetectOut(BaseModel):
    """POST /ingest/detect (#399, U27): what a statement file is and which account it fits.
    Nothing is stored. `candidate_account_ids`: the caller's open accounts of a fitting type
    and platform; `suggested_account_id`: the one to pre-select (exactly one candidate, or the
    one the statement's account number is linked to); `statement_last4`: the number's last four
    digits when the format names its account."""

    recognised: bool
    parser_key: Optional[str] = None
    file_label: Optional[str] = None
    account_types: List[str] = []
    candidate_account_ids: List[int] = []
    suggested_account_id: Optional[int] = None
    statement_last4: Optional[str] = None
