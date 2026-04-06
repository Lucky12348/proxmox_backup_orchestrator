from fastapi import APIRouter
from sqlalchemy import select

from app.api.dependencies import DbSession
from app.models import ExternalDisk
from app.schemas import ExternalBackupRunRead, ExternalBackupRunRequest, ExternalBackupRunSummaryRead
from app.services.external_backups import (
    get_external_backup_preview,
    get_external_backup_run,
    list_external_backup_runs,
    run_external_backup,
)


router = APIRouter(prefix="/external-backups", tags=["external-backups"])


@router.get("/preview/{disk_id}")
def get_preview(disk_id: int, db: DbSession) -> dict[str, str | bool]:
    return get_external_backup_preview(db, disk_id)


@router.post("/run", response_model=ExternalBackupRunSummaryRead)
def start_run(payload: ExternalBackupRunRequest, db: DbSession) -> ExternalBackupRunSummaryRead:
    run = run_external_backup(db, payload.disk_id, payload.confirmation)
    disk = db.get(ExternalDisk, run.disk_id)
    return _build_summary(run, disk.display_name if disk is not None else f"Disk {run.disk_id}")


@router.get("/runs", response_model=list[ExternalBackupRunSummaryRead])
def get_runs(db: DbSession) -> list[ExternalBackupRunSummaryRead]:
    runs = list_external_backup_runs(db)
    disk_names = {
        disk.id: disk.display_name
        for disk in db.scalars(select(ExternalDisk).where(ExternalDisk.id.in_([run.disk_id for run in runs])))
    }
    return [
        _build_summary(run, disk_names.get(run.disk_id, f"Disk {run.disk_id}"))
        for run in runs
    ]


@router.get("/runs/{run_id}", response_model=ExternalBackupRunRead)
def get_run(run_id: int, db: DbSession) -> ExternalBackupRunRead:
    run = get_external_backup_run(db, run_id)
    return ExternalBackupRunRead.model_validate(run)


def _build_summary(run, disk_name: str) -> ExternalBackupRunSummaryRead:
    return ExternalBackupRunSummaryRead(
        id=run.id,
        disk_id=run.disk_id,
        disk_name=disk_name,
        status=run.status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        target_path=run.target_path,
        datastore_name=run.datastore_name,
        message=run.message,
        stdout_log=run.stdout_log,
        stderr_log=run.stderr_log,
        command_summary=run.command_summary,
        return_code=run.return_code,
        mode=run.mode,
        created_at=run.created_at,
    )
