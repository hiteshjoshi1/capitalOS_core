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
    report_path: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ImportJobResponse(BaseModel):
    """GET /ingest/jobs/{job_id}: the job and its import report (the report file's JSON, or its
    text when it isn't JSON; null when there is none)."""

    job: ImportJobDetail
    report: Any = None


ImportJobList = List[ImportJobListItem]
