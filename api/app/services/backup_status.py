"""Backup status in the app (#399, U22, D-111).

The backups run on the Mac (scripts/db-backup.sh, launchd at BACKUP_TIME) into a folder the
API container can't see. After every backup, prune and `make backup-status`, the script writes
a small JSON file into the checkout's `state/` folder, which compose mounts read-only at
/app/state. This module reads it; nothing here touches the backups themselves.

The file holds no secrets and no paths: when the newest verified set was made, how many sets
are kept, whether they're encrypted, where they live (``icloud`` or ``local``), the daily time
and the Mac's UTC offset, and how the last run went.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.schemas.operations import BackupStatusOut

DEFAULT_STATUS_FILE = "/app/state/backup-status.json"
# Older than this, the backup is stale: amber on Data Hub and an Inbox item (#399).
STALE_AFTER_HOURS = 48
# Older than this (or a failed last run), the Inbox item is high.
VERY_STALE_HOURS = 7 * 24
LOCATION_LABELS = {"icloud": "iCloud Drive", "local": "on this Mac"}

_OFFSET_RE = re.compile(r"^([+-])(\d{2}):?(\d{2})$")
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


def status_file() -> str:
    return os.getenv("BACKUP_STATUS_FILE", DEFAULT_STATUS_FILE)


def _parse_dt(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _parse_offset(value: Any) -> Optional[timezone]:
    m = _OFFSET_RE.match(str(value or ""))
    if not m:
        return None
    sign = -1 if m.group(1) == "-" else 1
    return timezone(sign * timedelta(hours=int(m.group(2)), minutes=int(m.group(3))))


def _valid_time(value: Any) -> Optional[tuple[int, int]]:
    m = _TIME_RE.match(str(value or ""))
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    return int(m.group(1)), int(m.group(2))


def _time_label(value: Any) -> Optional[str]:
    hm = _valid_time(value)
    return f"{hm[0]:02d}:{hm[1]:02d}" if hm else None


def next_run_at(daily_time: Any, tz: Optional[timezone], now: datetime) -> Optional[datetime]:
    """The next daily run after ``now``, in the Mac's offset (a Mac asleep then runs it on wake)."""
    hm = _valid_time(daily_time)
    if hm is None or tz is None:
        return None
    hour, minute = hm
    local_now = now.astimezone(tz)
    candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= local_now:
        candidate += timedelta(days=1)
    return candidate


def read_status(path: Optional[str] = None) -> Optional[dict[str, Any]]:
    try:
        with open(path or status_file(), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def backup_status(now: Optional[datetime] = None, path: Optional[str] = None) -> BackupStatusOut:
    now = now or datetime.now(timezone.utc)
    data = read_status(path)
    if data is None:
        # A worktree, the test instance, or a Mac where no backup has run since #399.
        return BackupStatusOut(available=False)
    tz = _parse_offset(data.get("utc_offset"))
    newest = _parse_dt(data.get("newest_verified_at"))
    last_run = _parse_dt(data.get("last_run_at"))
    last_run_ok = data.get("last_run_ok") if isinstance(data.get("last_run_ok"), bool) else None
    age_hours = round((now - newest).total_seconds() / 3600, 1) if newest else None
    # A failed run after the newest good backup counts, so a broken job shows up the same day.
    last_run_failed = last_run_ok is False and last_run is not None and (newest is None or last_run > newest)
    stale = newest is None or (age_hours is not None and age_hours > STALE_AFTER_HOURS) or last_run_failed
    nxt = next_run_at(data.get("daily_time"), tz, now)
    location = data.get("location") if data.get("location") in LOCATION_LABELS else None
    sets = data.get("sets")
    return BackupStatusOut(
        available=True,
        last_verified_at=newest.isoformat() if newest else None,
        age_hours=age_hours,
        stale=stale,
        very_stale=newest is None or last_run_failed or (age_hours is not None and age_hours > VERY_STALE_HOURS),
        next_run_at=nxt.isoformat() if nxt else None,
        daily_time=_time_label(data.get("daily_time")),
        location=location,
        location_label=LOCATION_LABELS.get(location) if location else None,
        sets=sets if isinstance(sets, int) and sets >= 0 else None,
        encrypted=data.get("encrypted") if isinstance(data.get("encrypted"), bool) else None,
        last_run_at=last_run.isoformat() if last_run else None,
        last_run_ok=last_run_ok,
        status_written_at=(_parse_dt(data.get("written_at")) or now).isoformat() if data.get("written_at") else None,
    )
