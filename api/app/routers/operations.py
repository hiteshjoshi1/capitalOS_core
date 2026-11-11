"""The Data Hub inbox (#316): GET /operations/inbox; backup status (#399): GET /operations/backup-status."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth_context import CurrentUser, require_current_user
from app.db.session import get_db
from app.schemas.inbox import InboxResponse
from app.schemas.operations import BackupStatusOut
from app.services.backup_status import backup_status
from app.services.inbox import build_inbox

router = APIRouter(prefix="/operations", tags=["operations"], dependencies=[Depends(require_current_user)])


@router.get("/inbox", response_model=InboxResponse)
def operations_inbox(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    """What needs the caller, highest first, each with one action; what's fine, in
    one line each; the latest activity. Reads only."""
    return build_inbox(db, current_user)


@router.get("/backup-status", response_model=BackupStatusOut)
def operations_backup_status():
    """When the newest verified backup was made, the next daily run, and where the backups
    live (#399, D-111). Read from the status file the backup script writes; the same for
    every user, no paths or keys."""
    return backup_status()
