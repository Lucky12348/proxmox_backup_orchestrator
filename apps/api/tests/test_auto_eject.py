from datetime import datetime
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.external_backups import _build_summary
from app.db.base import Base
from app.models import BackupRunStatus, ExternalBackupMode, ExternalBackupRun, ExternalDisk
from app.services.disk_eject import _attempt_disk_spin_down
from app.services.external_backups import execute_external_backup_run, run_external_backup


class _SessionContext:
    def __init__(self, session: Session) -> None:
        self.session = session

    def __enter__(self) -> Session:
        return self.session

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None


class _NoActiveExportBridge:
    def inspect_external_export_objects(self):
        return SimpleNamespace(payload={"active": False})


class _FakeBackupExecutionService:
    def execute(self, **kwargs):
        step = SimpleNamespace(
            message="ok",
            stdout_log="stdout",
            stderr_log=None,
            command_summary="export",
            execution_cwd="/",
            return_code=0,
        )
        return SimpleNamespace(
            prepare=step,
            export=step,
            target_path="/mnt/pbo/disk/pbs-datastore",
            target_datastore_name=None,
        )


def _disk(**overrides) -> ExternalDisk:
    values = {
        "serial_number": "USB-123",
        "display_name": "Backup Disk",
        "capacity_gb": 1000,
        "connected": True,
        "dedicated_backup_disk": False,
        "allow_existing_data": False,
        "trusted": True,
        "reserved_capacity_gb": 0,
        "source": "agent",
        "active": True,
        "pbs_visible": False,
    }
    values.update(overrides)
    return ExternalDisk(**values)


def _run(disk_id: int, *, auto_eject_after_success: bool = False) -> ExternalBackupRun:
    now = datetime(2026, 5, 24, 12, 0, 0)
    return ExternalBackupRun(
        disk_id=disk_id,
        status=BackupRunStatus.PENDING,
        started_at=now,
        finished_at=None,
        target_path="/mnt/pbo/disk/pbs-datastore",
        datastore_name="backup-store",
        message=None,
        stdout_log=None,
        stderr_log=None,
        command_summary=None,
        execution_cwd=None,
        return_code=None,
        current_step="starting",
        progress_message=None,
        last_log_at=now,
        auto_eject_after_success=auto_eject_after_success,
        mode=ExternalBackupMode.DEDICATED,
        created_at=now,
    )


class AutoEjectAfterManualBackupTests(TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)

    def tearDown(self) -> None:
        self.session.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_build_summary_serializes_the_run_without_raising(self):
        # Regression guard: _build_summary() lists every ExternalBackupRunSummaryRead
        # field by hand instead of using model_validate(), so adding a field to the
        # schema without also adding it here raises a pydantic ValidationError at
        # request time (this broke GET /external-backups/runs in production once).
        disk = _disk()
        self.session.add(disk)
        self.session.commit()
        run = _run(disk.id, auto_eject_after_success=True)
        self.session.add(run)
        self.session.commit()

        summary = _build_summary(run, disk.display_name)

        self.assertTrue(summary.auto_eject_after_success)

    def test_run_external_backup_stores_the_requested_flag(self):
        disk = _disk()
        self.session.add(disk)
        self.session.commit()

        with patch("app.services.external_backups.get_external_backup_agent_bridge", return_value=_NoActiveExportBridge()):
            run = run_external_backup(self.session, disk.id, confirmation=True, auto_eject_after_success=True)

        self.assertTrue(run.auto_eject_after_success)

    def test_run_external_backup_defaults_to_no_auto_eject(self):
        disk = _disk()
        self.session.add(disk)
        self.session.commit()

        with patch("app.services.external_backups.get_external_backup_agent_bridge", return_value=_NoActiveExportBridge()):
            run = run_external_backup(self.session, disk.id, confirmation=True)

        self.assertFalse(run.auto_eject_after_success)

    def test_successful_manual_backup_ejects_an_eligible_disk_when_requested(self):
        disk = _disk(dedicated_backup_disk=True)
        self.session.add(disk)
        self.session.commit()
        run = _run(disk.id, auto_eject_after_success=True)
        self.session.add(run)
        self.session.commit()

        with (
            patch("app.services.external_backups.SessionLocal", return_value=_SessionContext(self.session)),
            patch("app.services.external_backups.handoff_disk_to_pbs", return_value=SimpleNamespace(message="handoff ok")),
            patch("app.services.external_backups.get_external_backup_execution_service", return_value=_FakeBackupExecutionService()),
            patch("app.services.disk_eject.eject_dedicated_external_disk") as eject_mock,
        ):
            execute_external_backup_run(run.id)

        eject_mock.assert_called_once_with(self.session, disk.id)

    def test_successful_manual_backup_does_not_eject_without_the_flag(self):
        disk = _disk(dedicated_backup_disk=True)
        self.session.add(disk)
        self.session.commit()
        run = _run(disk.id, auto_eject_after_success=False)
        self.session.add(run)
        self.session.commit()

        with (
            patch("app.services.external_backups.SessionLocal", return_value=_SessionContext(self.session)),
            patch("app.services.external_backups.handoff_disk_to_pbs", return_value=SimpleNamespace(message="handoff ok")),
            patch("app.services.external_backups.get_external_backup_execution_service", return_value=_FakeBackupExecutionService()),
            patch("app.services.disk_eject.eject_dedicated_external_disk") as eject_mock,
        ):
            execute_external_backup_run(run.id)

        eject_mock.assert_not_called()

    def test_auto_eject_is_skipped_for_a_disk_mode_that_does_not_support_it(self):
        disk = _disk(dedicated_backup_disk=False)
        self.session.add(disk)
        self.session.commit()
        run = _run(disk.id, auto_eject_after_success=True)
        self.session.add(run)
        self.session.commit()

        with (
            patch("app.services.external_backups.SessionLocal", return_value=_SessionContext(self.session)),
            patch("app.services.external_backups.handoff_disk_to_pbs", return_value=SimpleNamespace(message="handoff ok")),
            patch("app.services.external_backups.get_external_backup_execution_service", return_value=_FakeBackupExecutionService()),
            patch("app.services.disk_eject.eject_dedicated_external_disk") as eject_mock,
        ):
            execute_external_backup_run(run.id)

        eject_mock.assert_not_called()
        refreshed = self.session.get(ExternalBackupRun, run.id)
        self.assertIn("does not support it yet", refreshed.stdout_log or "")

    def test_auto_eject_failure_is_logged_but_does_not_fail_the_run(self):
        disk = _disk(dedicated_backup_disk=True)
        self.session.add(disk)
        self.session.commit()
        run = _run(disk.id, auto_eject_after_success=True)
        self.session.add(run)
        self.session.commit()

        with (
            patch("app.services.external_backups.SessionLocal", return_value=_SessionContext(self.session)),
            patch("app.services.external_backups.handoff_disk_to_pbs", return_value=SimpleNamespace(message="handoff ok")),
            patch("app.services.external_backups.get_external_backup_execution_service", return_value=_FakeBackupExecutionService()),
            patch("app.services.disk_eject.eject_dedicated_external_disk", side_effect=RuntimeError("agent unreachable")),
        ):
            execute_external_backup_run(run.id)

        refreshed = self.session.get(ExternalBackupRun, run.id)
        self.assertEqual(refreshed.status, BackupRunStatus.SUCCESS)
        self.assertIn("agent unreachable", refreshed.stderr_log or "")


class DiskSpinDownBestEffortTests(TestCase):
    def test_returns_the_agent_message_on_success(self):
        disk = _disk(id=1)
        fake_result = SimpleNamespace(payload={"message": "Disk spin-down/power-off attempted."})

        with patch("app.services.disk_eject.get_host_agent_client") as get_client:
            get_client.return_value.post.return_value = fake_result
            message = _attempt_disk_spin_down(disk)

        get_client.return_value.post.assert_called_once_with("/disk/spin-down", {"disk": "USB-123"})
        self.assertEqual(message, "Disk spin-down/power-off attempted.")

    def test_swallows_errors_instead_of_raising(self):
        disk = _disk(id=1)

        with patch("app.services.disk_eject.get_host_agent_client") as get_client:
            get_client.return_value.post.side_effect = RuntimeError("host agent unreachable")
            message = _attempt_disk_spin_down(disk)

        self.assertIn("host agent unreachable", message or "")
