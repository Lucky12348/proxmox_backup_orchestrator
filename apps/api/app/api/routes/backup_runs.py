from fastapi import APIRouter
from sqlalchemy import select

from app.api.dependencies import DbSession
from app.models import BackupRun
from app.schemas import BackupRunRead
from app.services.activity_cleanup import cleanup_backup_runs


router = APIRouter(prefix="/backup-runs", tags=["backup-runs"])


@router.get("", response_model=list[BackupRunRead])
def list_backup_runs(db: DbSession) -> list[BackupRun]:
    return list(db.scalars(select(BackupRun).order_by(BackupRun.started_at.desc())))


@router.delete("/cleanup")
def cleanup_runs(db: DbSession, keep_last: int = 10) -> dict[str, int]:
    deleted = cleanup_backup_runs(db, keep_last=keep_last)
    return {"deleted": deleted, "keep_last": keep_last}
