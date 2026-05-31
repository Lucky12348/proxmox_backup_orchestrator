from datetime import datetime
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models import (
    BackupRunStatus,
    ExternalBackupMode,
    ExternalBackupRun,
    ExternalDisk,
    ScheduledBackupEvent,
    ScheduledBackupRecurrenceType,
    ScheduledBackupRun,
    ScheduledBackupRunStatus,
    ScheduledBackupStartMode,
)
from app.schemas.agent import AgentDiskReportCreate
from app.api.routes.disks import update_disk
from app.schemas.external_disk import ExternalDiskUpdate
from app.services.disk_eject import eject_dedicated_external_disk
from app.services.disk_identity import canonical_serial_number, serials_match
from app.services.external_backup_agent import AgentCommandResult
from app.services.disks import ingest_agent_disk_report, list_preferred_disks


class DiskInventoryTests(TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)

    def tearDown(self) -> None:
        self.session.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_hex_ascii_serial_matches_plain_wd_serial(self):
        self.assertEqual(canonical_serial_number("575844324441314C31453743"), "WXD2DA1L1E7C")
        self.assertTrue(serials_match("575844324441314C31453743", "WXD2DA1L1E7C"))

    def test_wd_vendor_prefixed_serial_matches_plain_serial(self):
        self.assertEqual(canonical_serial_number("WD-WXD2DA1L1E7C"), "WXD2DA1L1E7C")
        self.assertTrue(serials_match("WD-WXD2DA1L1E7C", "WXD2DA1L1E7C"))

    def test_truncated_front_port_hex_serial_does_not_match_full_serial(self):
        self.assertEqual(canonical_serial_number("575844"), "575844")
        self.assertFalse(serials_match("575844", "WXD2DA1L1E7C"))

    def test_pbs_handoff_disk_is_not_deactivated_by_empty_agent_report(self):
        disk = _external_disk(
            serial_number="WD-WXD2DA1L1E7C",
            display_name="Western Digital Game Drive",
            source="agent",
            active=True,
            connected=True,
            handoff_status="attached_to_pbs",
            proxmox_usb_mapping="2-5",
            pbs_handoff_slot="usb0",
            pbs_visible=True,
            pbs_device_path="/dev/sdc",
            reported_by_hostname="promox",
        )
        self.session.add(disk)
        self.session.commit()

        ingest_agent_disk_report(
            self.session,
            AgentDiskReportCreate(
                hostname="promox",
                observed_at=datetime(2026, 5, 14, 12, 0, 0),
                disks=[],
            ),
        )

        refreshed = self.session.get(ExternalDisk, disk.id)
        self.assertIsNotNone(refreshed)
        self.assertTrue(refreshed.active)
        self.assertTrue(refreshed.connected)
        self.assertEqual(refreshed.handoff_status, "attached_to_pbs")
        self.assertEqual(refreshed.pbs_device_path, "/dev/sdc")

    def test_pbs_visible_disk_stays_in_preferred_disks(self):
        disk = _external_disk(
            serial_number="WD-WXD2DA1L1E7C",
            display_name="Western Digital Game Drive",
            source="agent",
            active=False,
            connected=True,
            pbs_visible=True,
            pbs_handoff_slot="usb0",
        )
        self.session.add(disk)
        self.session.commit()

        preferred = list_preferred_disks(self.session)

        self.assertEqual([item.serial_number for item in preferred], ["WD-WXD2DA1L1E7C"])

    def test_seed_disks_are_hidden_when_real_agent_disks_exist(self):
        seed_disk = _external_disk(
            serial_number="PBO-DISK-001",
            display_name="Seed Disk",
            source="seed",
            active=True,
            connected=True,
        )
        agent_disk = _external_disk(
            serial_number="WD-WXD2DA1L1E7C",
            display_name="Western Digital Game Drive",
            source="agent",
            active=False,
            connected=True,
            pbs_visible=True,
            pbs_handoff_slot="usb0",
        )
        self.session.add_all([seed_disk, agent_disk])
        self.session.commit()

        preferred = list_preferred_disks(self.session)

        self.assertEqual([item.serial_number for item in preferred], ["WD-WXD2DA1L1E7C"])

    def test_seed_disks_are_hidden_by_default_even_without_agent_disks(self):
        self.session.add(
            _external_disk(
                serial_number="PBO-DISK-001",
                display_name="Seed Disk",
                source="seed",
                active=True,
                connected=True,
            )
        )
        self.session.commit()

        preferred = list_preferred_disks(self.session)

        self.assertEqual(preferred, [])

    def test_seed_disks_can_be_shown_with_development_flag(self):
        self.session.add(
            _external_disk(
                serial_number="PBO-DISK-001",
                display_name="Seed Disk",
                source="seed",
                active=True,
                connected=True,
            )
        )
        self.session.commit()

        with patch("app.services.disks.get_settings", return_value=SimpleNamespace(show_seed_disks=True)):
            preferred = list_preferred_disks(self.session)

        self.assertEqual([item.serial_number for item in preferred], ["PBO-DISK-001"])

    def test_trusted_dedicated_agent_disk_remains_visible_after_eject_and_removal(self):
        disk = _external_disk(
            serial_number="WD-WXD2DA1L1E7C",
            display_name="Western Digital Game Drive",
            source="agent",
            active=False,
            connected=False,
            trusted=True,
            dedicated_backup_disk=True,
            handoff_status="ejected",
            pbs_visible=False,
            pbs_handoff_slot=None,
            pbs_device_path=None,
        )
        self.session.add(disk)
        self.session.commit()

        preferred = list_preferred_disks(self.session)

        self.assertEqual([item.serial_number for item in preferred], ["WD-WXD2DA1L1E7C"])
        self.assertFalse(preferred[0].connected)
        self.assertEqual(preferred[0].handoff_status, "ejected")

    def test_same_serial_on_different_usb_port_is_known_not_new(self):
        disk = _external_disk(
            serial_number="WD-WXD2DA1L1E7C",
            display_name="Western Digital Game Drive",
            source="agent",
            active=True,
            connected=False,
            presence_state="absent",
            proxmox_usb_mapping="2-5",
        )
        self.session.add(disk)
        self.session.commit()

        report = AgentDiskReportCreate(
            hostname="promox",
            observed_at=datetime(2026, 5, 31, 10, 0, 0),
            disks=[
                {
                    "serial_number": "WD-WXD2DA1L1E7C",
                    "display_name": "Western Digital Game Drive",
                    "model_name": "Game Drive",
                    "capacity_gb": 1000,
                    "filesystem_type": "ext4",
                    "mount_path": "/mnt/usb-new-port",
                    "detection_reason": "usb port 3-7",
                    "candidate_type": "usb",
                    "connected": True,
                    "trusted": True,
                }
            ],
        )

        with (
            patch("app.services.disks.notify_new_disk_detected") as new_notify,
            patch("app.services.disks.notify_known_disk_detected") as known_notify,
        ):
            ingest_agent_disk_report(self.session, report)

        new_notify.assert_not_called()
        known_notify.assert_called_once()
        disks = self.session.query(ExternalDisk).filter(ExternalDisk.serial_number.not_like("agent-report::%")).all()
        self.assertEqual(len(disks), 1)
        self.assertEqual(disks[0].canonical_serial_number, "WXD2DA1L1E7C")

    def test_hex_bridge_serial_updates_existing_disk_instead_of_creating_duplicate(self):
        disk = _external_disk(
            serial_number="WD-WXD2DA1L1E7C",
            reported_serial_number="WD-WXD2DA1L1E7C",
            canonical_serial_number="WXD2DA1L1E7C",
            serial_aliases=["WDWXD2DA1L1E7C", "WXD2DA1L1E7C"],
            display_name="WDC WD40NMZW-59BCBS0",
            model_name="WDC WD40NMZW-59BCBS0",
            source="agent",
            active=True,
            connected=False,
            presence_state="absent",
            trusted=True,
            dedicated_backup_disk=True,
            planning_notes="keep me",
            pbs_mount_path="/mnt/pbo/WD-WXD2DA1L1E7C/pbs-datastore",
            pbs_datastore_name="pbo-wd-wxd2da1l1e7c",
            prepared_as_pbs_datastore=True,
        )
        self.session.add(disk)
        self.session.commit()

        report = AgentDiskReportCreate(
            hostname="promox",
            observed_at=datetime(2026, 5, 31, 10, 0, 0),
            disks=[
                {
                    "serial_number": "575844324441314C31453743",
                    "display_name": "Game Drive",
                    "model_name": "Game Drive",
                    "capacity_gb": 4000,
                    "filesystem_type": "ext4",
                    "mount_path": "/mnt/front-usb",
                    "detection_reason": "usb port 1-2",
                    "candidate_type": "usb",
                    "connected": True,
                    "trusted": False,
                }
            ],
        )

        with (
            patch("app.services.disks.notify_new_disk_detected") as new_notify,
            patch("app.services.disks.notify_known_disk_detected") as known_notify,
        ):
            ingest_agent_disk_report(self.session, report)

        disks = self.session.query(ExternalDisk).filter(ExternalDisk.serial_number.not_like("agent-report::%")).all()
        self.assertEqual(len(disks), 1)
        refreshed = disks[0]
        self.assertEqual(refreshed.id, disk.id)
        self.assertEqual(refreshed.serial_number, "WD-WXD2DA1L1E7C")
        self.assertEqual(refreshed.reported_serial_number, "575844324441314C31453743")
        self.assertEqual(refreshed.reported_model_name, "Game Drive")
        self.assertEqual(refreshed.reported_mount_path, "/mnt/front-usb")
        self.assertEqual(refreshed.canonical_serial_number, "WXD2DA1L1E7C")
        self.assertIn("575844324441314C31453743", refreshed.serial_aliases)
        self.assertEqual(refreshed.display_name, "WDC WD40NMZW-59BCBS0")
        self.assertEqual(refreshed.pbs_mount_path, "/mnt/pbo/WD-WXD2DA1L1E7C/pbs-datastore")
        self.assertEqual(refreshed.pbs_datastore_name, "pbo-wd-wxd2da1l1e7c")
        self.assertTrue(refreshed.prepared_as_pbs_datastore)
        self.assertTrue(refreshed.trusted)
        self.assertTrue(refreshed.dedicated_backup_disk)
        self.assertEqual(refreshed.planning_notes, "keep me")
        new_notify.assert_not_called()
        known_notify.assert_called_once()
        description = known_notify.call_args.args[0]
        self.assertIn("Serie reportee: 575844324441314C31453743", description)
        self.assertIn("Serie canonique: WXD2DA1L1E7C", description)
        self.assertIn("Serie existante: WD-WXD2DA1L1E7C", description)
        self.assertIn("Detection: usb port 1-2", description)

    def test_zero_size_disk_is_marked_unusable_and_does_not_trigger_planning_or_notifications(self):
        report = AgentDiskReportCreate(
            hostname="promox",
            observed_at=datetime(2026, 5, 31, 10, 0, 0),
            disks=[
                {
                    "serial_number": "575844",
                    "display_name": "Game",
                    "model_name": "Game",
                    "capacity_gb": 0,
                    "filesystem_type": None,
                    "mount_path": None,
                    "detection_reason": "usb",
                    "candidate_type": "usb",
                    "connected": True,
                    "trusted": True,
                }
            ],
        )

        with (
            patch("app.services.disks.notify_new_disk_detected") as new_notify,
            patch("app.services.disks.notify_known_disk_detected") as known_notify,
            patch("app.services.disks.handle_disk_detected") as handle_detected,
        ):
            ingest_agent_disk_report(self.session, report)

        disk = self.session.scalar(select(ExternalDisk).where(ExternalDisk.serial_number == "575844"))
        self.assertIsNotNone(disk)
        self.assertEqual(disk.candidate_type, "unusable")
        self.assertEqual(
            disk.detection_reason,
            "Disque détecté mais taille 0B — port/câble/initialisation USB probablement défaillant.",
        )
        self.assertFalse(disk.trusted)
        self.assertFalse(disk.dedicated_backup_disk)
        self.assertFalse(disk.allow_existing_data)
        new_notify.assert_not_called()
        known_notify.assert_not_called()
        handle_detected.assert_not_called()

    def test_zero_size_disk_cannot_be_marked_trusted_or_dedicated(self):
        disk = _external_disk(
            serial_number="575844",
            display_name="Game",
            capacity_gb=0,
            candidate_type="unusable",
            source="agent",
            active=True,
            connected=True,
        )
        self.session.add(disk)
        self.session.commit()

        with self.assertRaises(HTTPException) as raised:
            update_disk(disk.id, ExternalDiskUpdate(trusted=True), self.session)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("taille 0B", raised.exception.detail)

    def test_planned_event_with_vendor_serial_starts_when_hex_serial_detected(self):
        event = ScheduledBackupEvent(
            title="Weekly backup",
            enabled=True,
            disk_serial="WD-WXD2DA1L1E7C",
            disk_label_or_model="WDC disk",
            datastore="backup-store",
            recurrence_type=ScheduledBackupRecurrenceType.ONCE,
            recurrence_config=None,
            timezone="Europe/Paris",
            window_starts_at=datetime(2026, 5, 31, 9, 0, 0),
            window_duration_minutes=180,
            notify_before_minutes=60,
            start_mode=ScheduledBackupStartMode.AUTO_ON_DISK_DETECTED,
            auto_eject_after_success=False,
            created_at=datetime(2026, 5, 31, 8, 0, 0),
            updated_at=datetime(2026, 5, 31, 8, 0, 0),
        )
        self.session.add(event)
        self.session.commit()
        report = AgentDiskReportCreate(
            hostname="promox",
            observed_at=datetime(2026, 5, 31, 10, 0, 0),
            disks=[
                {
                    "serial_number": "575844324441314C31453743",
                    "display_name": "Game Drive",
                    "model_name": "Game Drive",
                    "capacity_gb": 4000,
                    "filesystem_type": "ext4",
                    "mount_path": "/mnt/front-usb",
                    "detection_reason": "usb port 1-2",
                    "candidate_type": "usb",
                    "connected": True,
                    "trusted": True,
                }
            ],
        )

        with (
            patch("app.services.disks.notify_new_disk_detected"),
            patch("app.services.disks.notify_known_disk_detected"),
            patch("app.services.planning_scheduler.notify_expected_disk_detected"),
            patch("app.services.planning_scheduler.notify_planned_backup_started"),
            patch("app.services.planning_scheduler.run_external_backup", return_value=SimpleNamespace(id=123)),
            patch("app.services.planning_scheduler.threading.Thread", return_value=SimpleNamespace(start=lambda: None)),
        ):
            ingest_agent_disk_report(self.session, report)

        run = self.session.scalar(select(ScheduledBackupRun))
        self.assertIsNotNone(run)
        self.assertEqual(run.status, ScheduledBackupRunStatus.RUNNING)
        self.assertIsNotNone(run.disk_seen_at)
        self.assertEqual(run.backup_run_id, 123)

    def test_eject_refuses_when_external_backup_run_is_active(self):
        disk = _external_disk(
            serial_number="WD-WXD2DA1L1E7C",
            display_name="Western Digital Game Drive",
            dedicated_backup_disk=True,
            prepared_as_pbs_datastore=True,
        )
        self.session.add(disk)
        self.session.commit()
        self.session.add(_external_run(disk.id, BackupRunStatus.RUNNING))
        self.session.commit()

        with self.assertRaises(HTTPException) as raised:
            eject_dedicated_external_disk(self.session, disk.id)

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail, "Impossible d’éjecter le disque: une tâche PBS est en cours.")

    def test_eject_marks_disk_ejected_after_agent_unmount_and_vm_detach(self):
        disk = _external_disk(
            serial_number="WD-WXD2DA1L1E7C",
            display_name="Western Digital Game Drive",
            connected=True,
            dedicated_backup_disk=True,
            prepared_as_pbs_datastore=True,
            pbs_visible=True,
            pbs_handoff_slot="usb0",
            pbs_device_path="/dev/sdc",
            pbs_datastore_name="pbo-wd-wxd2da1l1e7c",
            pbs_mount_path="/mnt/pbo/WD-WXD2DA1L1E7C/pbs-datastore",
        )
        self.session.add(disk)
        self.session.commit()

        with (
            patch("app.services.disk_eject.get_external_backup_agent_bridge", return_value=_FakeEjectBridge()),
            patch("app.services.disk_eject._detach_usb_slot_via_host_agent", return_value=_host_agent_result()),
            patch("app.services.disk_eject._get_qemu_config_usb_map", return_value={}),
        ):
            result = eject_dedicated_external_disk(self.session, disk.id)

        self.assertFalse(result.connected)
        self.assertFalse(result.pbs_visible)
        self.assertIsNone(result.pbs_device_path)
        self.assertIsNone(result.pbs_handoff_slot)
        self.assertEqual(result.handoff_status, "ejected")

    def test_eject_keeps_handoff_state_when_pbs_unmount_succeeds_but_proxmox_detach_fails(self):
        disk = _external_disk(
            serial_number="WD-WXD2DA1L1E7C",
            display_name="Western Digital Game Drive",
            connected=True,
            dedicated_backup_disk=True,
            prepared_as_pbs_datastore=True,
            pbs_visible=True,
            pbs_handoff_slot="usb0",
            pbs_device_path="/dev/sdc",
            pbs_datastore_name="pbo-wd-wxd2da1l1e7c",
            pbs_mount_path="/mnt/pbo/WD-WXD2DA1L1E7C/pbs-datastore",
            handoff_status="visible_on_pbs",
        )
        self.session.add(disk)
        self.session.commit()

        with (
            patch("app.services.disk_eject.get_external_backup_agent_bridge", return_value=_FakeEjectBridge()),
            patch("app.services.disk_eject._detach_usb_slot_via_host_agent", return_value=_host_agent_result()),
            patch("app.services.disk_eject._get_qemu_config_usb_map", return_value={"usb0": "host=1058:2630,usb3=1"}),
            self.assertRaises(HTTPException) as raised,
        ):
            eject_dedicated_external_disk(self.session, disk.id)

        self.assertEqual(raised.exception.status_code, 502)
        self.assertEqual(
            raised.exception.detail,
            "Datastore démonté, mais USB encore attaché à la VM PBS. Ne retirez pas encore le disque.",
        )
        refreshed = self.session.get(ExternalDisk, disk.id)
        self.assertIsNotNone(refreshed)
        self.assertTrue(refreshed.pbs_visible)
        self.assertEqual(refreshed.pbs_device_path, "/dev/sdc")
        self.assertEqual(refreshed.pbs_handoff_slot, "usb0")
        self.assertEqual(refreshed.handoff_status, "visible_on_pbs")


def _external_disk(**overrides) -> ExternalDisk:
    values = {
        "serial_number": "disk",
        "display_name": "Disk",
        "capacity_gb": 0,
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
    now = datetime(2026, 5, 18, 12, 0, 0)
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


def _host_agent_result():
    return type("HostAgentResult", (), {"message": "ok"})()
