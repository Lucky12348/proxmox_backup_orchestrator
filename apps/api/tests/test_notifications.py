from datetime import datetime
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.base import Base
from app.models import BackupRunStatus, ExternalBackupMode, ExternalBackupRun, ExternalDisk
from app.services.disk_eject import eject_dedicated_external_disk
from app.services.external_backup_agent import AgentCommandResult
from app.services.external_backups import execute_external_backup_run
from app.services.maintenance import MaintenanceActionResult, MaintenanceCommandResult, MaintenanceComponentStatus
from app.services.notifications import NotificationService, notify_low_coverage


class _SessionContext:
    def __init__(self, session: Session) -> None:
        self.session = session

    def __enter__(self) -> Session:
        return self.session

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None


class NotificationServiceTests(TestCase):
    def test_status_masks_topic_and_omits_password(self):
        service = NotificationService(
            Settings(
                notifications_enabled=True,
                ntfy_base_url="https://ntfy.example.test",
                ntfy_topic="super-secret-topic",
                ntfy_username="pbo",
                ntfy_password="secret-password",
            )
        )

        status = service.status()

        self.assertEqual(status.topic, "supe...opic")
        self.assertEqual(status.username, "pbo")
        self.assertFalse(hasattr(status, "password"))

    def test_send_catches_ntfy_errors(self):
        service = NotificationService(
            Settings(
                notifications_enabled=True,
                ntfy_base_url="https://ntfy.example.test",
                ntfy_topic="topic",
                ntfy_username="pbo",
                ntfy_password="secret-password",
            )
        )

        with (
            patch("app.services.notifications.httpx.post", side_effect=RuntimeError("network secret-password")),
            self.assertLogs("app.services.notifications", level="WARNING") as logs,
        ):
            sent = service.send("title", "message")

        self.assertFalse(sent)
        self.assertIn("network ***", "\n".join(logs.output))
        self.assertNotIn("secret-password", "\n".join(logs.output))


class NotificationEventWiringTests(TestCase):
    def setUp(self) -> None:
        import app.services.notifications as notifications_module

        notifications_module._last_low_coverage_sent_at = None
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)

    def tearDown(self) -> None:
        self.session.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_backup_success_triggers_notify_once(self):
        disk = _external_disk(
            serial_number="USB-123",
            display_name="Backup Disk",
            model_name="Samsung T7",
            connected=True,
            trusted=True,
            dedicated_backup_disk=True,
        )
        self.session.add(disk)
        self.session.commit()
        run = _external_run(disk.id, BackupRunStatus.PENDING)
        self.session.add(run)
        self.session.commit()

        with (
            patch("app.services.external_backups.SessionLocal", return_value=_SessionContext(self.session)),
            patch("app.services.external_backups.handoff_disk_to_pbs", return_value=SimpleNamespace(message="handoff ok")),
            patch("app.services.external_backups.get_external_backup_execution_service", return_value=_FakeBackupExecutionService()),
            patch("app.services.external_backups.notify_backup_success") as notify_success,
            patch("app.services.external_backups.notify_backup_failure") as notify_failure,
        ):
            execute_external_backup_run(run.id)

        notify_success.assert_called_once()
        self.assertIn("USB-123", notify_success.call_args.args[0])
        self.assertIn("Samsung T7", notify_success.call_args.args[0])
        notify_failure.assert_not_called()

    def test_backup_failure_triggers_notify_once(self):
        disk = _external_disk(
            serial_number="USB-123",
            display_name="Backup Disk",
            connected=True,
            trusted=True,
            dedicated_backup_disk=True,
        )
        self.session.add(disk)
        self.session.commit()
        run = _external_run(disk.id, BackupRunStatus.PENDING)
        self.session.add(run)
        self.session.commit()

        with (
            patch("app.services.external_backups.SessionLocal", return_value=_SessionContext(self.session)),
            patch("app.services.external_backups.handoff_disk_to_pbs", return_value=SimpleNamespace(message="handoff ok")),
            patch("app.services.external_backups.get_external_backup_execution_service", return_value=_FailingBackupExecutionService()),
            patch("app.services.external_backups.notify_backup_success") as notify_success,
            patch("app.services.external_backups.notify_backup_failure") as notify_failure,
        ):
            execute_external_backup_run(run.id)

        notify_success.assert_not_called()
        notify_failure.assert_called_once()
        self.assertEqual(notify_failure.call_args.args[1], "failure")
        self.assertIn("export failed", notify_failure.call_args.args[2])

    def test_eject_success_triggers_notify_once(self):
        disk = _external_disk(
            serial_number="USB-123",
            connected=True,
            dedicated_backup_disk=True,
            prepared_as_pbs_datastore=True,
            pbs_visible=True,
            pbs_handoff_slot="usb0",
            pbs_device_path="/dev/sdc",
        )
        self.session.add(disk)
        self.session.commit()

        with (
            patch("app.services.disk_eject.get_external_backup_agent_bridge", return_value=_FakeEjectBridge()),
            patch("app.services.disk_eject._detach_usb_slot_via_host_agent", return_value=SimpleNamespace(message="ok")),
            patch("app.services.disk_eject._get_qemu_config_usb_map", return_value={}),
            patch("app.services.disk_eject.notify_disk_eject_ready") as notify_eject,
        ):
            eject_dedicated_external_disk(self.session, disk.id)

        notify_eject.assert_called_once_with("USB-123")

    def test_update_result_triggers_notify(self):
        from app.api.routes.maintenance import _action_read_with_notification

        result = MaintenanceActionResult(
            component="proxmox-agent",
            status=MaintenanceComponentStatus("proxmox-agent", "main", "abc", "def", "up_to_date", None, []),
            logs=[MaintenanceCommandResult("git pull", "ok", None, 0)],
            action_status="success",
        )

        with patch("app.api.routes.maintenance.notify_update_result") as notify_update:
            _action_read_with_notification(result)

        notify_update.assert_called_once_with("proxmox-agent", True, None)

    def test_low_coverage_has_cooldown(self):
        settings = Settings(
            notifications_enabled=True,
            ntfy_base_url="https://ntfy.example.test",
            ntfy_topic="topic",
        )
        with (
            patch("app.services.notifications.get_settings", return_value=settings),
            patch("app.services.notifications.get_notification_service") as service_factory,
        ):
            service_factory.return_value.send.return_value = True
            notify_low_coverage(50, 1, 2)
            notify_low_coverage(50, 1, 2)

        service_factory.return_value.send.assert_called_once()


def _external_disk(**overrides) -> ExternalDisk:
    values = {
        "serial_number": "disk",
        "display_name": "Disk",
        "capacity_gb": 1000,
        "connected": False,
        "dedicated_backup_disk": False,
        "allow_existing_data": False,
        "trusted": False,
        "reserved_capacity_gb": 0,
        "source": "agent",
        "active": True,
        "pbs_visible": False,
    }
    values.update(overrides)
    return ExternalDisk(**values)


def _external_run(disk_id: int, status: BackupRunStatus) -> ExternalBackupRun:
    now = datetime(2026, 5, 24, 12, 0, 0)
    return ExternalBackupRun(
        disk_id=disk_id,
        status=status,
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
        mode=ExternalBackupMode.DEDICATED,
        created_at=now,
    )


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


class _FailingBackupExecutionService:
    def execute(self, **kwargs):
        raise RuntimeError("export failed")


class _FakeEjectBridge:
    def eject_dedicated_pbs_datastore(self, *, serial: str, datastore_name: str, mount_path: str) -> AgentCommandResult:
        return AgentCommandResult(
            ok=True,
            message="ejected",
            stdout_log="unmounted",
            stderr_log=None,
            command_summary="sync\numount",
            execution_cwd="/",
            return_code=0,
            payload={},
        )
