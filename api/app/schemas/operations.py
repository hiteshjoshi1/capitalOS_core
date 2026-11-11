"""Data Hub extras (#399): backup status, and the settings facts the Settings page explains."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class BackupStatusOut(BaseModel):
    """GET /operations/backup-status (U22, D-111). `available` is false where no backup has
    reported yet (a worktree or the test instance). Times are ISO 8601 with an offset;
    `next_run_at` is in the Mac's offset (a Mac asleep then runs the job when it wakes).
    `stale`: no verified backup in 48 hours, or the last run failed; `very_stale`: over 7 days,
    or the last run failed. `location`: icloud or local. No paths or keys."""

    available: bool
    last_verified_at: Optional[str] = None
    age_hours: Optional[float] = None
    stale: bool = False
    very_stale: bool = False
    next_run_at: Optional[str] = None
    daily_time: Optional[str] = None
    location: Optional[str] = None
    location_label: Optional[str] = None
    sets: Optional[int] = None
    encrypted: Optional[bool] = None
    last_run_at: Optional[str] = None
    last_run_ok: Optional[bool] = None
    status_written_at: Optional[str] = None


class SettingsFactsOut(BaseModel):
    """GET /settings/facts (U24): how the app counts, read-only here.
    `snapshot_day`: the day of the month a month-end snapshot anchors on (SNAPSHOT_DAY).
    `upload_stale_days`: the default upload cadence before a source counts as overdue
    (UPLOAD_STALE_DAYS); each source's own cadence is set in Data Hub → Accounts & sources.
    `base_currencies`: the currencies the app can value everything in."""

    snapshot_day: int
    upload_stale_days: int
    base_currencies: List[str]
