import secrets

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, status
from sqlalchemy import select

from app.api.dependencies import DbSession
from app.core.config import get_settings
from app.models import ExternalDisk
from app.schemas import (
    ExternalBackupRunLogRequest,
    ExternalBackupRunRead,
    ExternalBackupRunRequest,
    ExternalBackupRunSummaryRead,
)
from app.services.external_backups import (
    append_external_backup_run_log,
    cleanup_external_backup_runs,
    delete_external_backup_run,
    execute_external_backup_run,
    get_external_backup_preview,
    get_external_backup_run,
    list_external_backup_runs,
    run_external_backup,
)


router = APIRouter(prefix="/external-backups", tags=["external-backups"])


@router.get("/preview/{disk_id}")
def get_preview(disk_id: int, db: DbSession) -> dict[str, str | bool | int | None]:
    return get_external_backup_preview(db, disk_id)


@router.post("/run", response_model=ExternalBackupRunSummaryRead)
def start_run(
    payload: ExternalBackupRunRequest,
    background_tasks: BackgroundTasks,
    db: DbSession,
) -> ExternalBackupRunSummaryRead:
    run = run_external_backup(db, payload.disk_id, payload.confirmation)
    background_tasks.add_task(execute_external_backup_run, run.id)
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


@router.delete("/runs/cleanup")
def cleanup_runs(db: DbSession, keep_last: int = 10) -> dict[str, int]:
    deleted = cleanup_external_backup_runs(db, keep_last=keep_last)
    return {"deleted": deleted, "keep_last": keep_last}


@router.get("/runs/{run_id}", response_model=ExternalBackupRunRead)
def get_run(run_id: int, db: DbSession) -> ExternalBackupRunRead:
    run = get_external_backup_run(db, run_id)
    return ExternalBackupRunRead.model_validate(run)


@router.delete("/runs/{run_id}", status_code=204)
def delete_run(run_id: int, db: DbSession) -> None:
    delete_external_backup_run(db, run_id)


@router.post("/runs/{run_id}/log", response_model=ExternalBackupRunRead)
def append_run_log(
    run_id: int,
    payload: ExternalBackupRunLogRequest,
    db: DbSession,
    x_agent_token: str | None = Header(default=None),
) -> ExternalBackupRunRead:
    settings = get_settings()
    if not settings.pbs_agent_token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="PBS_AGENT_TOKEN is not configured.",
        )
    if x_agent_token is None or not secrets.compare_digest(x_agent_token, settings.pbs_agent_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid agent token.")

    stream = "stderr" if payload.stderr_line else "stdout"
    run = append_external_backup_run_log(
        db,
        run_id,
        step=payload.step,
        message=payload.message,
        stream=stream,
        line=payload.stderr_line or payload.stdout_line,
        command=payload.command,
    )
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
        execution_cwd=run.execution_cwd,
        return_code=run.return_code,
        current_step=run.current_step,
        progress_message=run.progress_message,
        last_log_at=run.last_log_at,
        mode=run.mode,
        created_at=run.created_at,
    )
