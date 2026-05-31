from datetime import datetime
from unittest import TestCase
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models import BackupRunStatus, ExternalBackupMode, ExternalBackupRun, ExternalDisk
from app.services.external_backup_agent import AgentCommandResult
from app.services.external_backups import append_external_backup_run_log, run_external_backup


class ExternalBackupConflictProgressTests(TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)

    def tearDown(self) -> None:
        self.session.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_manual_backup_returns_409_if_db_active_run_exists(self):
        disk = _disk()
        self.session.add(disk)
        self.session.commit()
        self.session.add(_run(disk.id, BackupRunStatus.RUNNING))
        self.session.commit()

        with self.assertRaises(HTTPException) as raised:
            run_external_backup(self.session, disk.id, confirmation=True)

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail["active_run_id"], 1)

    def test_manual_backup_returns_409_if_pbs_active_export_exists(self):
        disk = _disk()
        self.session.add(disk)
        self.session.commit()

        with (
            patch("app.services.external_backups.get_external_backup_agent_bridge", return_value=_ActiveBridge()),
            self.assertRaises(HTTPException) as raised,
        ):
            run_external_backup(self.session, disk.id, confirmation=True)

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail["message"], "Un backup externe est deja en cours")

    def test_progress_parser_updates_external_run(self):
        disk = _disk()
        self.session.add(disk)
        self.session.commit()
        run = _run(disk.id, BackupRunStatus.RUNNING)
        self.session.add(run)
        self.session.commit()

        append_external_backup_run_log(self.session, run.id, step="sync_stdout", message="found 6 groups to sync", line="found 6 groups to sync")
        append_external_backup_run_log(self.session, run.id, step="sync_stdout", message="percentage done: 66.67% (4/6 groups)", line="percentage done: 66.67% (4/6 groups)")
        append_external_backup_run_log(self.session, run.id, step="sync_stdout", message="sync archive drive-scsi0.img.fidx", line="sync archive drive-scsi0.img.fidx")
        append_external_backup_run_log(self.session, run.id, step="sync_stdout", message="downloaded 17.372 GiB (2.371 MiB/s)", line="downloaded 17.372 GiB (2.371 MiB/s)")

        refreshed = self.session.get(ExternalBackupRun, run.id)
        self.assertEqual(refreshed.total_groups, 6)
        self.assertEqual(refreshed.completed_groups, 4)
        self.assertEqual(refreshed.progress_percent, 66.67)
        self.assertEqual(refreshed.current_archive, "drive-scsi0.img.fidx")
        self.assertEqual(refreshed.current_speed, "2.371 MiB/s")
        self.assertGreater(refreshed.downloaded_bytes, 17 * 1024**3)

    def test_group_lock_failure_is_structured(self):
        disk = _disk()
        self.session.add(disk)
        self.session.commit()
        run = _run(disk.id, BackupRunStatus.RUNNING)
        self.session.add(run)
        self.session.commit()

        append_external_backup_run_log(
            self.session,
            run.id,
            step="sync_stdout",
            message="sync group ct/103 failed - group lock failed",
            line="sync group ct/103 failed - group lock failed",
        )

        refreshed = self.session.get(ExternalBackupRun, run.id)
        self.assertEqual(refreshed.failed_groups, [{"group": "ct/103", "reason": "group lock failed"}])
        self.assertTrue(any("verrouille" in warning for warning in refreshed.warning_messages))


class _ActiveBridge:
    def inspect_external_export_objects(self):
        return AgentCommandResult(
            ok=True,
            message="active",
            stdout_log=None,
            stderr_log=None,
            command_summary="status",
            execution_cwd="/",
            return_code=0,
            payload={"active": True, "items": [{"kind": "sync-job", "name": "pbo-export-sync-test"}]},
        )


def _disk() -> ExternalDisk:
    return ExternalDisk(
        serial_number="WD-WXD2DA1L1E7C",
        display_name="WD",
        capacity_gb=1000,
        connected=True,
        dedicated_backup_disk=True,
        allow_existing_data=False,
        trusted=True,
        source="agent",
        active=True,
        presence_state="present",
    )


def _run(disk_id: int, status: BackupRunStatus) -> ExternalBackupRun:
    now = datetime(2026, 5, 31, 10, 0, 0)
    return ExternalBackupRun(
        disk_id=disk_id,
        status=status,
        started_at=now,
        finished_at=None,
        target_path="/mnt/pbo/WD-WXD2DA1L1E7C/pbs-datastore",
        datastore_name="backup-store",
        message=None,
        stdout_log=None,
        stderr_log=None,
        command_summary=None,
        execution_cwd=None,
        return_code=None,
        current_step=None,
        progress_message=None,
        last_log_at=now,
        mode=ExternalBackupMode.DEDICATED,
        created_at=now,
    )
