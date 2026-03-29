from datetime import datetime

from sqlalchemy import select

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import BackupRun, BackupRunStatus, DiskAssignment, ExternalDisk, VMType, VirtualMachine


def create_tables() -> None:
    Base.metadata.create_all(bind=engine)


def seed_database() -> None:
    with SessionLocal() as db:
        if db.scalar(select(VirtualMachine.id).limit(1)) is not None:
            return

        vm_alpha = VirtualMachine(
            name="vm-app-01",
            vm_type=VMType.VM,
            critical=True,
            size_gb=120,
            enabled=True,
            last_backup_at=datetime.fromisoformat("2026-03-28T22:10:00"),
        )
        vm_beta = VirtualMachine(
            name="vm-db-01",
            vm_type=VMType.VM,
            critical=True,
            size_gb=240,
            enabled=True,
            last_backup_at=datetime.fromisoformat("2026-03-28T22:15:00"),
        )
        ct_logs = VirtualMachine(
            name="ct-logs-01",
            vm_type=VMType.CT,
            critical=False,
            size_gb=40,
            enabled=True,
            last_backup_at=None,
        )
        ct_lab = VirtualMachine(
            name="ct-lab-01",
            vm_type=VMType.CT,
            critical=False,
            size_gb=25,
            enabled=False,
            last_backup_at=None,
        )

        disk_primary = ExternalDisk(
            serial_number="PBO-DISK-001",
            display_name="Vault Alpha",
            capacity_gb=2000,
            connected=True,
            dedicated_backup_disk=True,
            allow_existing_data=False,
            preferred_root_path="/mnt/pbs-alpha",
            notes="Primary rotating backup disk.",
        )
        disk_secondary = ExternalDisk(
            serial_number="PBO-DISK-002",
            display_name="Vault Beta",
            capacity_gb=4000,
            connected=False,
            dedicated_backup_disk=True,
            allow_existing_data=True,
            preferred_root_path="/mnt/pbs-beta",
            notes="Off-site disk currently disconnected.",
        )
        disk_shared = ExternalDisk(
            serial_number="PBO-DISK-003",
            display_name="Shared Utility Disk",
            capacity_gb=1000,
            connected=True,
            dedicated_backup_disk=False,
            allow_existing_data=True,
            preferred_root_path=None,
            notes="General-purpose external storage.",
        )

        db.add_all(
            [
                vm_alpha,
                vm_beta,
                ct_logs,
                ct_lab,
                disk_primary,
                disk_secondary,
                disk_shared,
            ]
        )
        db.flush()

        db.add_all(
            [
                DiskAssignment(disk_id=disk_primary.id, vm_id=vm_alpha.id, pinned=True),
                DiskAssignment(disk_id=disk_primary.id, vm_id=vm_beta.id, pinned=True),
                DiskAssignment(disk_id=disk_secondary.id, vm_id=ct_logs.id, pinned=False),
                BackupRun(
                    status=BackupRunStatus.SUCCESS,
                    started_at=datetime.fromisoformat("2026-03-28T22:00:00"),
                    finished_at=datetime.fromisoformat("2026-03-28T22:18:00"),
                    triggered_by="schedule",
                    summary="Nightly backup completed for vm-app-01 and vm-db-01.",
                ),
                BackupRun(
                    status=BackupRunStatus.FAILED,
                    started_at=datetime.fromisoformat("2026-03-27T22:00:00"),
                    finished_at=datetime.fromisoformat("2026-03-27T22:07:00"),
                    triggered_by="manual",
                    summary="Backup interrupted because Vault Beta was not connected.",
                ),
            ]
        )

        db.commit()
