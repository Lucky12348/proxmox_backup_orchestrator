from datetime import datetime, timedelta
from unittest import TestCase

from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.routes.planning import create_event, delete_event, get_calendar_occurrences, list_events, update_event
from app.db.base import Base
from app.models import (
    BackupRunStatus,
    ExternalDisk,
    ExternalBackupMode,
    ExternalBackupRun,
    ScheduledBackupEvent,
    ScheduledBackupRecurrenceType,
    ScheduledBackupRun,
    ScheduledBackupRunStatus,
    ScheduledBackupStartMode,
)
from app.schemas.planning import ScheduledBackupEventCreate, ScheduledBackupEventUpdate
from app.services.planning_scheduler import expand_occurrences, process_runs


class PlanningEventTests(TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)

    def tearDown(self) -> None:
        self.session.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_cannot_delete_event_with_active_run(self):
        event = _event()
        self.session.add(event)
        self.session.commit()
        self.session.add(_run(event.id, ScheduledBackupRunStatus.WAITING_FOR_DISK))
        self.session.commit()

        with self.assertRaises(HTTPException) as raised:
            delete_event(event.id, self.session)

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail, "Cannot delete event while a run is active. Cancel the run first.")

    def test_soft_delete_hides_event_and_keeps_runs(self):
        event = _event()
        self.session.add(event)
        self.session.commit()
        run = _run(event.id, ScheduledBackupRunStatus.FAILURE)
        self.session.add(run)
        self.session.commit()

        delete_event(event.id, self.session)

        self.assertEqual(list_events(self.session), [])
        stored_run = self.session.get(ScheduledBackupRun, run.id)
        self.assertIsNotNone(stored_run)
        stored_event = self.session.get(ScheduledBackupEvent, event.id)
        self.assertIsNotNone(stored_event)
        self.assertIsNotNone(stored_event.deleted_at)

    def test_weekly_event_expands_in_visible_range(self):
        event = _event(window_starts_at=datetime(2026, 5, 4, 1, 0, 0))
        occurrences = expand_occurrences(
            event,
            datetime(2026, 5, 1, 0, 0, 0),
            datetime(2026, 5, 31, 23, 59, 59),
        )

        self.assertEqual(
            [item.date().isoformat() for item in occurrences],
            ["2026-05-04", "2026-05-11", "2026-05-18", "2026-05-25"],
        )

    def test_calendar_endpoint_expands_weekly_event_across_month(self):
        event = _event(window_starts_at=datetime(2026, 5, 4, 1, 0, 0))
        self.session.add(event)
        self.session.commit()

        occurrences = get_calendar_occurrences(
            self.session,
            start=datetime(2026, 5, 1).date(),
            end=datetime(2026, 5, 31).date(),
        )

        self.assertEqual(
            [item.window_starts_at.date().isoformat() for item in occurrences],
            ["2026-05-04", "2026-05-11", "2026-05-18", "2026-05-25"],
        )
        self.assertEqual(occurrences[0].title, "Weekly backup")
        self.assertEqual(occurrences[0].disk_serial, "USB-123")

    def test_delete_missing_event_returns_not_found_not_500(self):
        with self.assertRaises(HTTPException) as raised:
            delete_event(999, self.session)

        self.assertEqual(raised.exception.status_code, 404)

    def test_started_occurrence_after_window_is_not_marked_missed(self):
        event = _event()
        self.session.add(event)
        self.session.commit()
        backup = _external_run(BackupRunStatus.RUNNING)
        self.session.add(backup)
        self.session.commit()
        run = _run(event.id, ScheduledBackupRunStatus.RUNNING)
        run.disk_seen_at = run.window_starts_at
        run.backup_run_id = backup.id
        run.started_at = run.window_starts_at
        self.session.add(run)
        self.session.commit()

        process_runs(self.session, run.window_ends_at + timedelta(minutes=1))

        self.assertEqual(self.session.get(ScheduledBackupRun, run.id).status, ScheduledBackupRunStatus.RUNNING)

    def test_linked_backup_success_updates_planned_occurrence_success(self):
        event = _event()
        self.session.add(event)
        self.session.commit()
        backup = _external_run(BackupRunStatus.SUCCESS)
        self.session.add(backup)
        self.session.commit()
        run = _run(event.id, ScheduledBackupRunStatus.RUNNING)
        run.backup_run_id = backup.id
        self.session.add(run)
        self.session.commit()

        process_runs(self.session, run.window_starts_at + timedelta(minutes=10))

        self.assertEqual(self.session.get(ScheduledBackupRun, run.id).status, ScheduledBackupRunStatus.SUCCESS)

    def test_linked_backup_failure_updates_planned_occurrence_failure(self):
        event = _event()
        self.session.add(event)
        self.session.commit()
        backup = _external_run(BackupRunStatus.FAILED)
        backup.message = "sync failed"
        self.session.add(backup)
        self.session.commit()
        run = _run(event.id, ScheduledBackupRunStatus.RUNNING)
        run.backup_run_id = backup.id
        self.session.add(run)
        self.session.commit()

        process_runs(self.session, run.window_starts_at + timedelta(minutes=10))

        refreshed = self.session.get(ScheduledBackupRun, run.id)
        self.assertEqual(refreshed.status, ScheduledBackupRunStatus.FAILURE)
        self.assertEqual(refreshed.error, "sync failed")

    def test_create_event_rejects_auto_eject_for_non_dedicated_disk(self):
        self.session.add(_disk())
        self.session.commit()

        with self.assertRaises(HTTPException) as raised:
            create_event(
                ScheduledBackupEventCreate(
                    **{
                        **_event_payload(),
                        "auto_eject_after_success": True,
                    }
                ),
                self.session,
            )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(
            raised.exception.detail,
            "L'auto-eject planifie est disponible uniquement pour les disques dedies PBS.",
        )

    def test_create_event_accepts_auto_eject_for_dedicated_disk(self):
        self.session.add(_disk(dedicated_backup_disk=True))
        self.session.commit()

        event = create_event(
            ScheduledBackupEventCreate(
                **{
                    **_event_payload(),
                    "auto_eject_after_success": True,
                }
            ),
            self.session,
        )

        self.assertTrue(event.auto_eject_after_success)

    def test_update_event_rejects_enabling_auto_eject_for_non_dedicated_disk(self):
        self.session.add(_disk())
        event = _event(auto_eject_after_success=False)
        self.session.add(event)
        self.session.commit()

        with self.assertRaises(HTTPException) as raised:
            update_event(event.id, ScheduledBackupEventUpdate(auto_eject_after_success=True), self.session)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertFalse(self.session.get(ScheduledBackupEvent, event.id).auto_eject_after_success)


def _event(**overrides) -> ScheduledBackupEvent:
    now = datetime(2026, 5, 1, 12, 0, 0)
    values = {
        "title": "Weekly backup",
        "enabled": True,
        "disk_serial": "USB-123",
        "disk_label_or_model": "Disk USB-123",
        "datastore": "backup-store",
        "recurrence_type": ScheduledBackupRecurrenceType.WEEKLY,
        "recurrence_config": None,
        "timezone": "Europe/Paris",
        "window_starts_at": datetime(2026, 5, 3, 1, 0, 0),
        "window_duration_minutes": 300,
        "notify_before_minutes": 60,
        "start_mode": ScheduledBackupStartMode.MANUAL_CONFIRMATION,
        "auto_eject_after_success": False,
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return ScheduledBackupEvent(**values)


def _run(event_id: int, status: ScheduledBackupRunStatus) -> ScheduledBackupRun:
    start = datetime(2026, 5, 3, 1, 0, 0)
    return ScheduledBackupRun(
        event_id=event_id,
        scheduled_for=start,
        window_starts_at=start,
        window_ends_at=start + timedelta(hours=5),
        status=status,
        created_at=start,
        updated_at=start,
    )


def _external_run(status: BackupRunStatus) -> ExternalBackupRun:
    now = datetime(2026, 5, 3, 1, 0, 0)
    return ExternalBackupRun(
        disk_id=1,
        status=status,
        started_at=now,
        finished_at=now + timedelta(minutes=5) if status in {BackupRunStatus.SUCCESS, BackupRunStatus.FAILED} else None,
        target_path="/mnt/pbo/USB-123/pbs-datastore",
        datastore_name="backup-store",
        message=None,
        stdout_log=None,
        stderr_log=None,
        command_summary=None,
        execution_cwd=None,
        return_code=0 if status == BackupRunStatus.SUCCESS else None,
        current_step=None,
        progress_message=None,
        last_log_at=now,
        mode=ExternalBackupMode.DEDICATED,
        created_at=now,
    )


def _disk(**overrides) -> ExternalDisk:
    values = {
        "serial_number": "USB-123",
        "display_name": "Disk USB-123",
        "capacity_gb": 1000,
        "connected": True,
        "dedicated_backup_disk": False,
        "allow_existing_data": True,
        "trusted": True,
        "reserved_capacity_gb": 0,
        "source": "agent",
        "active": True,
        "pbs_visible": False,
        "prepared_as_pbs_datastore": False,
    }
    values.update(overrides)
    return ExternalDisk(**values)


def _event_payload() -> dict:
    payload = _event().__dict__.copy()
    payload.pop("id", None)
    payload.pop("_sa_instance_state", None)
    return payload
