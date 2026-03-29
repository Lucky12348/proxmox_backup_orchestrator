from fastapi import APIRouter
from sqlalchemy import select

from app.api.dependencies import DbSession
from app.models import BackupRun
from app.schemas import BackupRunRead


router = APIRouter(prefix="/backup-runs", tags=["backup-runs"])


@router.get("", response_model=list[BackupRunRead])
def list_backup_runs(db: DbSession) -> list[BackupRun]:
    return list(db.scalars(select(BackupRun).order_by(BackupRun.started_at.desc())))
