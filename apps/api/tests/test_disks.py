from datetime import datetime
from unittest import TestCase

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models import ExternalDisk
from app.schemas.agent import AgentDiskReportCreate
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
