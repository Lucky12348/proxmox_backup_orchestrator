from datetime import datetime, timedelta
from unittest import TestCase

from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models import BackupRun, BackupRunStatus, DiskPreparationMode, DiskPreparationRun, ExternalBackupMode, ExternalBackupRun
from app.services.activity_cleanup import cleanup_backup_runs, cleanup_disk_preparation_runs
from app.services.external_backups import cleanup_external_backup_runs, delete_external_backup_run


class ActivityCleanupTests(TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.now = datetime(2026, 5, 18, 12, 0, 0)

    def tearDown(self) -> None:
        self.session.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_external_cleanup_deletes_only_old_failed_runs(self):
        for index in range(12):
            self.session.add(
                _external_run(
                    index + 1,
                    BackupRunStatus.FAILED,
                    self.now - timedelta(minutes=index),
                )
            )
        running = _external_run(100, BackupRunStatus.RUNNING, self.now - timedelta(days=1))
        success = _external_run(101, BackupRunStatus.SUCCESS, self.now - timedelta(days=2))
        self.session.add_all([running, success])
        self.session.commit()

        deleted = cleanup_external_backup_runs(self.session, keep_last=10)

        remaining = list(self.session.scalars(select(ExternalBackupRun)))
        remaining_ids = {run.id for run in remaining}
        self.assertEqual(deleted, 2)
        self.assertIn(running.id, remaining_ids)
        self.assertIn(success.id, remaining_ids)
        self.assertTrue(all(run.status != BackupRunStatus.RUNNING or run.id == running.id for run in remaining))

    def test_external_delete_rejects_active_runs(self):
        run = _external_run(1, BackupRunStatus.PENDING, self.now)
        self.session.add(run)
        self.session.commit()

        with self.assertRaises(HTTPException) as raised:
            delete_external_backup_run(self.session, run.id)

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIsNotNone(self.session.get(ExternalBackupRun, run.id))

    def test_backup_cleanup_deletes_old_failed_runs_only(self):
        for index in range(4):
            self.session.add(_backup_run(index + 1, BackupRunStatus.FAILED, self.now - timedelta(minutes=index)))
        self.session.add(_backup_run(10, BackupRunStatus.RUNNING, self.now - timedelta(days=1)))
        self.session.add(_backup_run(11, BackupRunStatus.SUCCESS, self.now - timedelta(days=2)))
        self.session.commit()

        deleted = cleanup_backup_runs(self.session, keep_last=2)

        remaining = list(self.session.scalars(select(BackupRun)))
        self.assertEqual(deleted, 2)
        self.assertTrue(any(run.status == BackupRunStatus.RUNNING for run in remaining))
        self.assertTrue(any(run.status == BackupRunStatus.SUCCESS for run in remaining))

    def test_disk_preparation_cleanup_deletes_old_failed_runs_only(self):
        for index in range(3):
            self.session.add(_disk_preparation_run(index + 1, BackupRunStatus.FAILED, self.now - timedelta(minutes=index)))
        self.session.add(_disk_preparation_run(10, BackupRunStatus.RUNNING, self.now - timedelta(days=1)))
        self.session.commit()

        deleted = cleanup_disk_preparation_runs(self.session, keep_last=1)

        remaining = list(self.session.scalars(select(DiskPreparationRun)))
        self.assertEqual(deleted, 2)
        self.assertTrue(any(run.status == BackupRunStatus.RUNNING for run in remaining))


def _external_run(run_id: int, status: BackupRunStatus, started_at: datetime) -> ExternalBackupRun:
    return ExternalBackupRun(
        id=run_id,
        disk_id=1,
        status=status,
        started_at=started_at,
        finished_at=started_at if status in {BackupRunStatus.SUCCESS, BackupRunStatus.FAILED} else None,
        target_path="/mnt/pbo/example/pbs-datastore",
        datastore_name="backup",
        message=None,
        stdout_log=None,
        stderr_log=None,
        command_summary=None,
        execution_cwd=None,
        return_code=None,
        current_step=None,
        progress_message=None,
        last_log_at=None,
        mode=ExternalBackupMode.DEDICATED,
        created_at=started_at,
    )


def _backup_run(run_id: int, status: BackupRunStatus, started_at: datetime) -> BackupRun:
    return BackupRun(
        id=run_id,
        status=status,
        started_at=started_at,
        finished_at=started_at if status in {BackupRunStatus.SUCCESS, BackupRunStatus.FAILED} else None,
        triggered_by="test",
        summary=None,
    )


def _disk_preparation_run(run_id: int, status: BackupRunStatus, started_at: datetime) -> DiskPreparationRun:
    return DiskPreparationRun(
        id=run_id,
        disk_id=1,
        mode=DiskPreparationMode.PRESERVE_EXISTING_DATA,
        status=status,
        started_at=started_at,
        finished_at=started_at if status in {BackupRunStatus.SUCCESS, BackupRunStatus.FAILED} else None,
        message=None,
        mount_path=None,
        filesystem_type=None,
        created_at=started_at,
    )
