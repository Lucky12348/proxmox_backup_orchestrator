from datetime import datetime
from unittest import TestCase
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models import BackupRunStatus, ExternalBackupMode, ExternalBackupRun, ExternalDisk
from app.schemas.agent import AgentDiskReportCreate
from app.services.disk_eject import eject_dedicated_external_disk
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
            patch("app.services.disk_eject.ProxmoxClient", return_value=_FakeProxmoxClient({})),
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
            patch("app.services.disk_eject.ProxmoxClient", return_value=_FakeProxmoxClient({"usb0": "host=1058:2630,usb3=1"})),
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


class _FakeProxmoxClient:
    def __init__(self, vm_config):
        self.vm_config = vm_config

    def delete_qemu_usb_device(self, node_name: str, vm_id: int, slot: str) -> None:
        if self.vm_config.get("_delete_fails"):
            raise RuntimeError("delete failed")

    def get_qemu_config(self, node_name: str, vm_id: int) -> dict:
        return self.vm_config
