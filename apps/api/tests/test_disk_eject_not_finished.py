from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.base import Base
from app.models import BackupRunStatus, ExternalBackupRun, ExternalDisk
from app.services.disk_eject import (
    EJECT_NOT_FINISHED_MESSAGE,
    EJECT_NOT_FINISHED_STEP,
    eject_dedicated_external_disk,
)
from app.services.external_backup_agent import AgentCommandError, AgentCommandResult
from app.services.external_backups import append_external_backup_run_log
from app.services.notifications import notify_disk_eject_not_finished

AGENT_TIMEOUT_MESSAGE = (
    "Éjection non terminée : l'écriture des données sur le disque n'est pas finie après 1800 s "
    "(Dirty 2.0 GiB, Writeback 50.0 MiB). NE PAS débrancher le disque."
)


class _NotFinishedBridge:
    """PBS agent whose `sync -f` timed out after streaming progress into the run log."""

    def __init__(self, engine) -> None:
        self.engine = engine
        self.run_ids: list[int | None] = []

    def eject_dedicated_pbs_datastore(self, *, serial, datastore_name, mount_path, run_id=None):
        self.run_ids.append(run_id)
        # The agent's progress callback writes through a separate API request/session.
        with Session(self.engine) as callback_session:
            append_external_backup_run_log(
                callback_session,
                run_id,
                step="eject_flush",
                message="Écriture en cours vers le disque (15 s écoulées) : Dirty 2.0 GiB, Writeback 50.0 MiB.",
            )
        raise AgentCommandError(
            "PBS agent returned 500: " + AGENT_TIMEOUT_MESSAGE,
            stdout_log=None,
            stderr_log=AGENT_TIMEOUT_MESSAGE,
            command_summary="eject-dedicated-pbs-datastore",
            execution_cwd="/",
            return_code=1,
            payload={"ok": False, "error_code": "eject_not_finished", "message": AGENT_TIMEOUT_MESSAGE},
        )


class _SuccessBridge:
    def __init__(self, engine) -> None:
        self.engine = engine

    def eject_dedicated_pbs_datastore(self, *, serial, datastore_name, mount_path, run_id=None):
        with Session(self.engine) as callback_session:
            append_external_backup_run_log(
                callback_session, run_id, step="eject_flush", message="Écriture en cours (15 s écoulées)."
            )
        return AgentCommandResult(
            ok=True,
            message="ejected",
            stdout_log="Cache d'écriture vidé en 3 s.",
            stderr_log=None,
            command_summary="sync -f\numount",
            execution_cwd="/",
            return_code=0,
            payload={},
        )


class EjectNotFinishedTests(TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.disk = ExternalDisk(
            serial_number="WD-WXD2DA1L1E7C",
            display_name="Western Digital Game Drive",
            capacity_gb=0,
            connected=True,
            dedicated_backup_disk=True,
            allow_existing_data=False,
            trusted=False,
            reserved_capacity_gb=0,
            source="agent",
            active=True,
            prepared_as_pbs_datastore=True,
            pbs_visible=True,
            pbs_handoff_slot="usb0",
            pbs_device_path="/dev/sdc",
            pbs_datastore_name="pbo-wd-wxd2da1l1e7c",
            pbs_mount_path="/mnt/pbo/WD-WXD2DA1L1E7C/pbs-datastore",
        )
        self.session.add(self.disk)
        self.session.commit()

    def tearDown(self) -> None:
        self.session.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _eject(self, bridge):
        with (
            patch("app.services.disk_eject.get_external_backup_agent_bridge", return_value=bridge),
            patch("app.services.disk_eject._detach_usb_slot_via_host_agent", return_value=SimpleNamespace(message="ok")) as detach,
            patch("app.services.disk_eject._get_qemu_config_usb_map", return_value={}),
            patch("app.services.disk_eject._attempt_disk_spin_down", return_value=None) as spin_down,
            patch("app.services.disk_eject.notify_disk_eject_not_finished") as notify_not_finished,
            patch("app.services.disk_eject.notify_disk_eject_ready") as notify_ready,
        ):
            try:
                outcome = eject_dedicated_external_disk(self.session, self.disk.id)
            except HTTPException as exc:
                outcome = exc
        return outcome, detach, spin_down, notify_not_finished, notify_ready

    def _runs(self) -> list[ExternalBackupRun]:
        return list(self.session.scalars(select(ExternalBackupRun).order_by(ExternalBackupRun.id)))

    def test_flush_timeout_keeps_disk_attached_and_reports_do_not_unplug(self):
        bridge = _NotFinishedBridge(self.engine)

        outcome, detach, spin_down, notify_not_finished, notify_ready = self._eject(bridge)

        self.assertIsInstance(outcome, HTTPException)
        self.assertEqual(outcome.status_code, 504)
        self.assertEqual(outcome.detail, EJECT_NOT_FINISHED_MESSAGE)
        self.assertIn("NE PAS débrancher le disque", EJECT_NOT_FINISHED_MESSAGE)
        detach.assert_not_called()
        spin_down.assert_not_called()
        notify_ready.assert_not_called()
        notify_not_finished.assert_called_once_with("WD-WXD2DA1L1E7C", "PBS agent returned 500: " + AGENT_TIMEOUT_MESSAGE)

        disk = self.session.get(ExternalDisk, self.disk.id)
        self.assertTrue(disk.connected)
        self.assertTrue(disk.pbs_visible)
        self.assertEqual(disk.pbs_handoff_slot, "usb0")
        self.assertNotEqual(disk.handoff_status, "ejected")

        [run] = self._runs()
        self.assertEqual(bridge.run_ids, [run.id])
        self.assertEqual(run.status, BackupRunStatus.FAILED)
        self.assertEqual(run.current_step, EJECT_NOT_FINISHED_STEP)
        self.assertEqual(run.message, EJECT_NOT_FINISHED_MESSAGE)
        # Progress streamed by the agent during the flush is kept.
        self.assertIn("Écriture en cours vers le disque", run.stdout_log)

    def test_retrying_the_eject_after_a_timeout_succeeds(self):
        self._eject(_NotFinishedBridge(self.engine))

        outcome, detach, _, notify_not_finished, notify_ready = self._eject(_SuccessBridge(self.engine))

        self.assertIsInstance(outcome, ExternalDisk)
        self.assertEqual(outcome.handoff_status, "ejected")
        detach.assert_called_once()
        notify_not_finished.assert_not_called()
        notify_ready.assert_called_once_with("WD-WXD2DA1L1E7C")
        first, retry = self._runs()
        self.assertEqual(first.current_step, EJECT_NOT_FINISHED_STEP)
        self.assertEqual(retry.status, BackupRunStatus.SUCCESS)
        # Flush progress streamed during the retry survives the final run update.
        self.assertIn("Écriture en cours (15 s écoulées).", retry.stdout_log)
        self.assertIn("Cache d'écriture vidé en 3 s.", retry.stdout_log)


class EjectNotFinishedNotificationTests(TestCase):
    def _send(self, enabled_events: set[str]):
        settings = Settings(notifications_enabled=True, ntfy_base_url="https://ntfy.example.test", ntfy_topic="topic")
        with (
            patch("app.services.notifications.get_settings", return_value=settings),
            patch("app.services.notifications._event_enabled", side_effect=lambda name, _settings: name in enabled_events),
            patch("app.services.notifications.get_notification_service") as service_factory,
        ):
            service_factory.return_value.send.return_value = True
            notify_disk_eject_not_finished("WD-WXD2DA1L1E7C", "Dirty 2.0 GiB")
        return service_factory.return_value.send

    def test_sends_high_priority_do_not_unplug_alert(self):
        send = self._send({"disk_eject_ready"})

        send.assert_called_once()
        title, body = send.call_args.args
        self.assertIn("NE PAS debrancher", title)
        self.assertIn("NE PAS debrancher le disque", body)
        self.assertIn("WD-WXD2DA1L1E7C", body)
        self.assertEqual(send.call_args.kwargs["priority"], "high")

    def test_sent_when_only_failure_alerts_are_enabled(self):
        self._send({"backup_failure"}).assert_called_once()

    def test_not_sent_when_eject_and_failure_alerts_are_disabled(self):
        self._send(set()).assert_not_called()
