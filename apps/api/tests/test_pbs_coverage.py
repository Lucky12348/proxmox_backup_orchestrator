from datetime import datetime
from unittest import TestCase

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models import AssetIgnore, BackupRunStatus, ExternalBackupMode, ExternalBackupRun, ExternalDisk, VMType, VirtualMachine
from app.services.overview import get_overview_metrics
from app.services.pbs_sync import sync_pbs_inventory


class FakePBSClient:
    def list_snapshots(self, datastore_name: str) -> list[dict]:
        return [
            {"backup-id": "vm/100", "backup-time": "2026-05-21T20:00:00Z"},
            {"backup-id": "ct/200", "backup-time": "2026-05-21T21:00:00Z"},
        ]


class PBSCoverageTests(TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)

    def tearDown(self) -> None:
        self.session.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_coverage_uses_pbs_snapshots_not_external_backup_runs(self):
        disk = ExternalDisk(
            serial_number="USB-1",
            display_name="USB disk",
            capacity_gb=1000,
            connected=True,
            dedicated_backup_disk=True,
            allow_existing_data=False,
            source="agent",
            active=True,
        )
        self.session.add_all(
            [
                VirtualMachine(
                    name="vm-100",
                    vm_type=VMType.VM,
                    enabled=True,
                    source="proxmox",
                    external_id="100",
                    last_backup_at=None,
                ),
                VirtualMachine(
                    name="ct-200",
                    vm_type=VMType.CT,
                    enabled=True,
                    source="proxmox",
                    external_id="200",
                    last_backup_at=None,
                ),
                VirtualMachine(
                    name="vm-300",
                    vm_type=VMType.VM,
                    enabled=True,
                    source="proxmox",
                    external_id="300",
                    last_backup_at=None,
                ),
                disk,
            ]
        )
        self.session.flush()
        self.session.add(
            ExternalBackupRun(
                disk_id=disk.id,
                status=BackupRunStatus.SUCCESS,
                started_at=datetime(2026, 5, 20, 20, 0, 0),
                finished_at=datetime(2026, 5, 20, 21, 0, 0),
                target_path="/mnt/export",
                datastore_name="external",
                message="Unrelated external export",
                mode=ExternalBackupMode.DEDICATED,
                created_at=datetime(2026, 5, 20, 20, 0, 0),
            )
        )
        self.session.commit()

        sync_pbs_inventory(self.session, client=FakePBSClient())
        metrics = get_overview_metrics(self.session)

        self.assertEqual(metrics.total_vms, 3)
        self.assertEqual(metrics.protected_vms, 2)
        self.assertEqual(metrics.coverage_percent, 66.7)

    def test_coverage_excludes_ignored_assets(self):
        self.session.add_all(
            [
                VirtualMachine(
                    name="vm-100",
                    vm_type=VMType.VM,
                    enabled=True,
                    source="proxmox",
                    node_name="pve",
                    external_id="100",
                    last_backup_at=datetime(2026, 5, 21, 20, 0, 0),
                ),
                VirtualMachine(
                    name="vm-200",
                    vm_type=VMType.VM,
                    enabled=True,
                    source="proxmox",
                    node_name="pve",
                    external_id="200",
                    last_backup_at=None,
                ),
                AssetIgnore(source="proxmox", node="pve", vmid="200", ignored=True),
            ]
        )
        self.session.commit()

        metrics = get_overview_metrics(self.session)

        self.assertEqual(metrics.total_vms, 1)
        self.assertEqual(metrics.protected_vms, 1)
        self.assertEqual(metrics.ignored_vms, 1)
        self.assertEqual(metrics.coverage_percent, 100.0)
