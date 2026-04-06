from datetime import datetime

from sqlalchemy import inspect, select, text

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import (
    BackupRun,
    BackupRunStatus,
    DiskAssignment,
    DiskPreparationMode,
    DiskPreparationRun,
    ExternalBackupMode,
    ExternalBackupRun,
    ExternalDisk,
    VMType,
    VirtualMachine,
)


def create_tables() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_virtual_machine_schema()
    ensure_external_disk_schema()
    ensure_external_backup_run_schema()
    ensure_disk_preparation_run_schema()


def ensure_virtual_machine_schema() -> None:
    inspector = inspect(engine)
    existing_columns = {column["name"] for column in inspector.get_columns("virtual_machines")}
    column_statements = {
        "source": "ALTER TABLE virtual_machines ADD COLUMN source VARCHAR(32) NOT NULL DEFAULT 'seed'",
        "external_id": "ALTER TABLE virtual_machines ADD COLUMN external_id VARCHAR(64)",
        "node_name": "ALTER TABLE virtual_machines ADD COLUMN node_name VARCHAR(255)",
        "runtime_status": "ALTER TABLE virtual_machines ADD COLUMN runtime_status VARCHAR(64)",
        "last_seen_at": "ALTER TABLE virtual_machines ADD COLUMN last_seen_at TIMESTAMP",
    }

    with engine.begin() as connection:
        for column_name, statement in column_statements.items():
            if column_name not in existing_columns:
                connection.execute(text(statement))

        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "ix_virtual_machines_source_external_id "
                "ON virtual_machines (source, external_id) "
                "WHERE external_id IS NOT NULL"
            )
        )


def ensure_external_disk_schema() -> None:
    inspector = inspect(engine)
    existing_columns = {column["name"] for column in inspector.get_columns("external_disks")}
    column_statements = {
        "filesystem_type": "ALTER TABLE external_disks ADD COLUMN filesystem_type VARCHAR(64)",
        "model_name": "ALTER TABLE external_disks ADD COLUMN model_name VARCHAR(255)",
        "mount_path": "ALTER TABLE external_disks ADD COLUMN mount_path VARCHAR(255)",
        "last_seen_at": "ALTER TABLE external_disks ADD COLUMN last_seen_at TIMESTAMP",
        "detection_reason": "ALTER TABLE external_disks ADD COLUMN detection_reason VARCHAR(255)",
        "candidate_type": "ALTER TABLE external_disks ADD COLUMN candidate_type VARCHAR(64)",
        "trusted": "ALTER TABLE external_disks ADD COLUMN trusted BOOLEAN NOT NULL DEFAULT FALSE",
        "usable_capacity_gb": "ALTER TABLE external_disks ADD COLUMN usable_capacity_gb INTEGER",
        "reserved_capacity_gb": "ALTER TABLE external_disks ADD COLUMN reserved_capacity_gb INTEGER NOT NULL DEFAULT 0",
        "planning_notes": "ALTER TABLE external_disks ADD COLUMN planning_notes TEXT",
        "source": "ALTER TABLE external_disks ADD COLUMN source VARCHAR(32) NOT NULL DEFAULT 'seed'",
        "reported_by_hostname": "ALTER TABLE external_disks ADD COLUMN reported_by_hostname VARCHAR(255)",
        "active": "ALTER TABLE external_disks ADD COLUMN active BOOLEAN NOT NULL DEFAULT TRUE",
    }

    with engine.begin() as connection:
        for column_name, statement in column_statements.items():
            if column_name not in existing_columns:
                connection.execute(text(statement))


def ensure_external_backup_run_schema() -> None:
    inspector = inspect(engine)
    if "external_backup_runs" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("external_backup_runs")}
    column_statements = {
        "created_at": (
            "ALTER TABLE external_backup_runs "
            "ADD COLUMN created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
        ),
        "stdout_log": "ALTER TABLE external_backup_runs ADD COLUMN stdout_log TEXT",
        "stderr_log": "ALTER TABLE external_backup_runs ADD COLUMN stderr_log TEXT",
        "command_summary": "ALTER TABLE external_backup_runs ADD COLUMN command_summary TEXT",
    }

    with engine.begin() as connection:
        for column_name, statement in column_statements.items():
            if column_name not in existing_columns:
                connection.execute(text(statement))


def ensure_disk_preparation_run_schema() -> None:
    inspector = inspect(engine)
    if "disk_preparation_runs" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("disk_preparation_runs")}
    column_statements = {
        "created_at": (
            "ALTER TABLE disk_preparation_runs "
            "ADD COLUMN created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
        ),
    }

    with engine.begin() as connection:
        for column_name, statement in column_statements.items():
            if column_name not in existing_columns:
                connection.execute(text(statement))


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
            source="seed",
            last_backup_at=datetime.fromisoformat("2026-03-28T22:10:00"),
        )
        vm_beta = VirtualMachine(
            name="vm-db-01",
            vm_type=VMType.VM,
            critical=True,
            size_gb=240,
            enabled=True,
            source="seed",
            last_backup_at=datetime.fromisoformat("2026-03-28T22:15:00"),
        )
        ct_logs = VirtualMachine(
            name="ct-logs-01",
            vm_type=VMType.CT,
            critical=False,
            size_gb=40,
            enabled=True,
            source="seed",
            last_backup_at=None,
        )
        ct_lab = VirtualMachine(
            name="ct-lab-01",
            vm_type=VMType.CT,
            critical=False,
            size_gb=25,
            enabled=False,
            source="seed",
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
            filesystem_type="ext4",
            model_name="Seeded Backup Disk Alpha",
            mount_path="/mnt/pbs-alpha",
            last_seen_at=datetime.fromisoformat("2026-03-28T20:00:00"),
            detection_reason="seeded development disk",
            candidate_type="seed",
            trusted=False,
            usable_capacity_gb=None,
            reserved_capacity_gb=0,
            planning_notes=None,
            source="seed",
            active=True,
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
            filesystem_type="ext4",
            model_name="Seeded Backup Disk Beta",
            mount_path=None,
            last_seen_at=datetime.fromisoformat("2026-03-27T18:00:00"),
            detection_reason="seeded development disk",
            candidate_type="seed",
            trusted=False,
            usable_capacity_gb=None,
            reserved_capacity_gb=0,
            planning_notes=None,
            source="seed",
            active=True,
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
            filesystem_type="exfat",
            model_name="Seeded Utility Disk",
            mount_path="/mnt/shared-utility",
            last_seen_at=datetime.fromisoformat("2026-03-28T19:30:00"),
            detection_reason="seeded development disk",
            candidate_type="seed",
            trusted=False,
            usable_capacity_gb=None,
            reserved_capacity_gb=0,
            planning_notes=None,
            source="seed",
            active=True,
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
                ExternalBackupRun(
                    disk_id=disk_primary.id,
                    status=BackupRunStatus.SUCCESS,
                    started_at=datetime.fromisoformat("2026-03-28T23:00:00"),
                    finished_at=datetime.fromisoformat("2026-03-28T23:12:00"),
                    target_path="/mnt/pbs-alpha/pbs-datastore",
                    datastore_name="backup",
                    message="Seeded external export completed to dedicated target.",
                    stdout_log="TASK OK\nSummary: synced datastore backup to /mnt/pbs-alpha/pbs-datastore",
                    stderr_log=None,
                    command_summary="proxmox-backup-manager sync-job run pbo-seeded-export",
                    mode=ExternalBackupMode.DEDICATED,
                    created_at=datetime.fromisoformat("2026-03-28T23:00:00"),
                ),
                DiskPreparationRun(
                    disk_id=disk_primary.id,
                    mode=DiskPreparationMode.DEDICATED_BACKUP,
                    status=BackupRunStatus.SUCCESS,
                    started_at=datetime.fromisoformat("2026-03-28T19:45:00"),
                    finished_at=datetime.fromisoformat("2026-03-28T19:50:00"),
                    message="Seeded preparation mounted the dedicated disk at /mnt/pbs-alpha.",
                    mount_path="/mnt/pbs-alpha",
                    filesystem_type="ext4",
                    created_at=datetime.fromisoformat("2026-03-28T19:45:00"),
                ),
            ]
        )

        db.commit()
