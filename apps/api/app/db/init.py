from datetime import datetime

from sqlalchemy import inspect, select, text

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import (
    AssetIgnore,
    BackupRun,
    BackupRunStatus,
    DiskAssignment,
    DiskPreparationMode,
    DiskPreparationRun,
    ExternalBackupMode,
    ExternalBackupRun,
    ExternalDisk,
    NotificationPreferences,
    ScheduledBackupEvent,
    ScheduledBackupRun,
    VMType,
    VirtualMachine,
)


def create_tables() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_virtual_machine_schema()
    ensure_external_disk_schema()
    ensure_external_backup_run_schema()
    ensure_disk_preparation_run_schema()
    ensure_scheduled_backup_schema()
    ensure_notification_preferences_schema()
    ensure_asset_ignore_schema()


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
        "handoff_status": "ALTER TABLE external_disks ADD COLUMN handoff_status VARCHAR(32)",
        "proxmox_usb_mapping": "ALTER TABLE external_disks ADD COLUMN proxmox_usb_mapping VARCHAR(255)",
        "pbs_handoff_slot": "ALTER TABLE external_disks ADD COLUMN pbs_handoff_slot VARCHAR(32)",
        "pbs_visible": "ALTER TABLE external_disks ADD COLUMN pbs_visible BOOLEAN NOT NULL DEFAULT FALSE",
        "pbs_device_path": "ALTER TABLE external_disks ADD COLUMN pbs_device_path VARCHAR(255)",
        "pbs_datastore_name": "ALTER TABLE external_disks ADD COLUMN pbs_datastore_name VARCHAR(255)",
        "pbs_mount_path": "ALTER TABLE external_disks ADD COLUMN pbs_mount_path VARCHAR(512)",
        "pbs_filesystem_type": "ALTER TABLE external_disks ADD COLUMN pbs_filesystem_type VARCHAR(64)",
        "prepared_as_pbs_datastore": (
            "ALTER TABLE external_disks ADD COLUMN prepared_as_pbs_datastore BOOLEAN NOT NULL DEFAULT FALSE"
        ),
        "presence_state": "ALTER TABLE external_disks ADD COLUMN presence_state VARCHAR(16) NOT NULL DEFAULT 'absent'",
        "last_detection_notified_at": "ALTER TABLE external_disks ADD COLUMN last_detection_notified_at TIMESTAMP",
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
        "execution_cwd": "ALTER TABLE external_backup_runs ADD COLUMN execution_cwd VARCHAR(512)",
        "return_code": "ALTER TABLE external_backup_runs ADD COLUMN return_code INTEGER",
        "current_step": "ALTER TABLE external_backup_runs ADD COLUMN current_step VARCHAR(128)",
        "progress_message": "ALTER TABLE external_backup_runs ADD COLUMN progress_message TEXT",
        "last_log_at": "ALTER TABLE external_backup_runs ADD COLUMN last_log_at TIMESTAMP",
        "progress_percent": "ALTER TABLE external_backup_runs ADD COLUMN progress_percent FLOAT",
        "total_groups": "ALTER TABLE external_backup_runs ADD COLUMN total_groups INTEGER",
        "completed_groups": "ALTER TABLE external_backup_runs ADD COLUMN completed_groups INTEGER",
        "current_group": "ALTER TABLE external_backup_runs ADD COLUMN current_group VARCHAR(255)",
        "current_snapshot": "ALTER TABLE external_backup_runs ADD COLUMN current_snapshot VARCHAR(255)",
        "current_archive": "ALTER TABLE external_backup_runs ADD COLUMN current_archive VARCHAR(255)",
        "downloaded_bytes": "ALTER TABLE external_backup_runs ADD COLUMN downloaded_bytes BIGINT",
        "current_speed": "ALTER TABLE external_backup_runs ADD COLUMN current_speed VARCHAR(64)",
        "last_progress_at": "ALTER TABLE external_backup_runs ADD COLUMN last_progress_at TIMESTAMP",
        "warning_messages": "ALTER TABLE external_backup_runs ADD COLUMN warning_messages JSON",
        "failed_groups": "ALTER TABLE external_backup_runs ADD COLUMN failed_groups JSON",
        "pbs_sync_job_id": "ALTER TABLE external_backup_runs ADD COLUMN pbs_sync_job_id VARCHAR(255)",
        "pbs_remote_id": "ALTER TABLE external_backup_runs ADD COLUMN pbs_remote_id VARCHAR(255)",
        "pbs_task_upid": "ALTER TABLE external_backup_runs ADD COLUMN pbs_task_upid TEXT",
        "elapsed_seconds": "ALTER TABLE external_backup_runs ADD COLUMN elapsed_seconds INTEGER",
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


def ensure_scheduled_backup_schema() -> None:
    Base.metadata.create_all(bind=engine, tables=[ScheduledBackupEvent.__table__, ScheduledBackupRun.__table__])
    inspector = inspect(engine)
    existing_columns = {column["name"] for column in inspector.get_columns("scheduled_backup_events")}
    if "deleted_at" not in existing_columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE scheduled_backup_events ADD COLUMN deleted_at TIMESTAMP"))


def ensure_notification_preferences_schema() -> None:
    Base.metadata.create_all(bind=engine, tables=[NotificationPreferences.__table__])
    inspector = inspect(engine)
    if "notification_preferences" not in inspector.get_table_names():
        return
    existing_columns = {column["name"] for column in inspector.get_columns("notification_preferences")}
    column_statements = {
        "notifications_enabled_override": "ALTER TABLE notification_preferences ADD COLUMN notifications_enabled_override BOOLEAN",
        "notify_on_disk_new_detected": "ALTER TABLE notification_preferences ADD COLUMN notify_on_disk_new_detected BOOLEAN NOT NULL DEFAULT TRUE",
        "notify_on_disk_known_detected": "ALTER TABLE notification_preferences ADD COLUMN notify_on_disk_known_detected BOOLEAN NOT NULL DEFAULT TRUE",
        "notify_on_planned_disk_detected": "ALTER TABLE notification_preferences ADD COLUMN notify_on_planned_disk_detected BOOLEAN NOT NULL DEFAULT TRUE",
        "notify_on_planned_backup_reminder": "ALTER TABLE notification_preferences ADD COLUMN notify_on_planned_backup_reminder BOOLEAN NOT NULL DEFAULT TRUE",
        "notify_on_planned_backup_started": "ALTER TABLE notification_preferences ADD COLUMN notify_on_planned_backup_started BOOLEAN NOT NULL DEFAULT TRUE",
        "notify_on_planned_confirmation_required": "ALTER TABLE notification_preferences ADD COLUMN notify_on_planned_confirmation_required BOOLEAN NOT NULL DEFAULT TRUE",
        "notify_on_planned_backup_missed": "ALTER TABLE notification_preferences ADD COLUMN notify_on_planned_backup_missed BOOLEAN NOT NULL DEFAULT TRUE",
    }
    with engine.begin() as connection:
        for column_name, statement in column_statements.items():
            if column_name not in existing_columns:
                connection.execute(text(statement))


def ensure_asset_ignore_schema() -> None:
    Base.metadata.create_all(bind=engine, tables=[AssetIgnore.__table__])
    inspector = inspect(engine)
    if "asset_ignores" not in inspector.get_table_names():
        return
    existing_columns = {column["name"] for column in inspector.get_columns("asset_ignores")}
    column_statements = {
        "source": "ALTER TABLE asset_ignores ADD COLUMN source VARCHAR(32) NOT NULL DEFAULT 'proxmox'",
        "node": "ALTER TABLE asset_ignores ADD COLUMN node VARCHAR(255) NOT NULL DEFAULT ''",
        "vmid": "ALTER TABLE asset_ignores ADD COLUMN vmid VARCHAR(64) NOT NULL DEFAULT ''",
        "ignored": "ALTER TABLE asset_ignores ADD COLUMN ignored BOOLEAN NOT NULL DEFAULT FALSE",
        "reason": "ALTER TABLE asset_ignores ADD COLUMN reason TEXT",
        "updated_at": "ALTER TABLE asset_ignores ADD COLUMN updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP",
    }
    with engine.begin() as connection:
        for column_name, statement in column_statements.items():
            if column_name not in existing_columns:
                connection.execute(text(statement))
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "ix_asset_ignores_source_node_vmid "
                "ON asset_ignores (source, node, vmid)"
            )
        )


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
            allow_existing_data=False,
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
            dedicated_backup_disk=True,
            allow_existing_data=False,
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
                    execution_cwd="/mnt/pbs-alpha",
                    return_code=0,
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
