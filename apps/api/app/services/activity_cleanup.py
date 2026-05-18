from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BackupRun, BackupRunStatus, DiskPreparationRun


def cleanup_backup_runs(db: Session, keep_last: int = 10) -> int:
    runs = list(db.scalars(select(BackupRun).order_by(BackupRun.started_at.desc())))
    return _delete_old_failed_runs(db, runs, keep_last)


def cleanup_disk_preparation_runs(db: Session, keep_last: int = 10) -> int:
    runs = list(db.scalars(select(DiskPreparationRun).order_by(DiskPreparationRun.started_at.desc())))
    return _delete_old_failed_runs(db, runs, keep_last)


def _delete_old_failed_runs(db: Session, runs, keep_last: int) -> int:
    keep_last = max(0, keep_last)
    protected_ids = {
        run.id
        for run in runs[:keep_last]
    } | {
        run.id
        for run in runs
        if run.status in {BackupRunStatus.PENDING, BackupRunStatus.RUNNING}
    }
    deletable = [
        run
        for run in runs
        if run.status == BackupRunStatus.FAILED and run.id not in protected_ids
    ]

    for run in deletable:
        db.delete(run)
    db.commit()
    return len(deletable)
