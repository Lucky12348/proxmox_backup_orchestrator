from datetime import datetime, timedelta
from unittest import TestCase

from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.routes.planning import delete_event, list_events
from app.db.base import Base
from app.models import (
    ScheduledBackupEvent,
    ScheduledBackupRecurrenceType,
    ScheduledBackupRun,
    ScheduledBackupRunStatus,
    ScheduledBackupStartMode,
)
from app.services.planning_scheduler import expand_occurrences


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

    def test_delete_missing_event_returns_not_found_not_500(self):
        with self.assertRaises(HTTPException) as raised:
            delete_event(999, self.session)

        self.assertEqual(raised.exception.status_code, 404)


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
