from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.models import (
    BackupRunStatus,
    ExternalBackupRun,
    ExternalDisk,
    ScheduledBackupEvent,
    ScheduledBackupRecurrenceType,
    ScheduledBackupRun,
    ScheduledBackupRunStatus,
    ScheduledBackupStartMode,
)
from app.services.disk_eject import eject_dedicated_external_disk
from app.services.disk_identity import serial_aliases, serials_match
from app.services.external_backups import execute_external_backup_run, run_external_backup
from app.services.notifications import (
    notify_backup_failure,
    notify_expected_disk_detected,
    notify_planned_backup_missed,
    notify_planned_backup_reminder,
    notify_planned_backup_started,
    notify_planned_confirmation_required,
)


logger = logging.getLogger(__name__)
_scheduler_stop = threading.Event()
_scheduler_thread: threading.Thread | None = None


def start_planning_scheduler(settings: Settings | None = None) -> None:
    current_settings = settings or get_settings()
    if not current_settings.planning_scheduler_enabled:
        return
    global _scheduler_thread
    if _scheduler_thread is not None and _scheduler_thread.is_alive():
        return
    _scheduler_stop.clear()
    _scheduler_thread = threading.Thread(
        target=_scheduler_loop,
        args=(current_settings.planning_scheduler_interval_seconds,),
        daemon=True,
        name="pbo-planning-scheduler",
    )
    _scheduler_thread.start()


def stop_planning_scheduler() -> None:
    _scheduler_stop.set()
    if _scheduler_thread is not None:
        _scheduler_thread.join(timeout=2)


def scheduler_tick(now: datetime | None = None) -> None:
    current_time = now or datetime.utcnow()
    with SessionLocal() as db:
        create_due_runs(db, current_time)
        process_runs(db, current_time)


def create_due_runs(db: Session, now: datetime) -> None:
    horizon = now + timedelta(hours=24)
    events = list(
        db.scalars(
            select(ScheduledBackupEvent).where(
                ScheduledBackupEvent.enabled.is_(True),
                ScheduledBackupEvent.deleted_at.is_(None),
            )
        )
    )
    for event in events:
        for occurrence in expand_occurrences(event, now - timedelta(hours=24), horizon):
            _ensure_run(db, event, occurrence)
    db.commit()


def process_runs(db: Session, now: datetime) -> None:
    runs = list(
        db.scalars(
            select(ScheduledBackupRun).where(
                ScheduledBackupRun.status.in_(
                    [
                        ScheduledBackupRunStatus.PENDING,
                        ScheduledBackupRunStatus.WAITING_FOR_DISK,
                        ScheduledBackupRunStatus.WAITING_FOR_CONFIRMATION,
                        ScheduledBackupRunStatus.WAITING_FOR_EXTERNAL_BACKUP,
                        ScheduledBackupRunStatus.RUNNING,
                    ]
                )
            )
        )
    )
    for run in runs:
        event = db.get(ScheduledBackupEvent, run.event_id)
        if event is None or not event.enabled or event.deleted_at is not None:
            continue
        _process_run(db, event, run, now)
    db.commit()


def handle_disk_detected(db: Session, disk: ExternalDisk, now: datetime | None = None) -> None:
    current_time = now or datetime.utcnow()
    events = list(
        db.scalars(
            select(ScheduledBackupEvent).where(
                ScheduledBackupEvent.enabled.is_(True),
                ScheduledBackupEvent.deleted_at.is_(None),
            )
        )
    )
    events = [event for event in events if _disk_matches_event_serial(disk, event.disk_serial)]
    for event in events:
        for occurrence in expand_occurrences(event, current_time - timedelta(hours=24), current_time + timedelta(hours=1)):
            _ensure_run(db, event, occurrence)
    db.commit()

    runs = list(
        db.scalars(
            select(ScheduledBackupRun).where(
                ScheduledBackupRun.status.in_(
                    [ScheduledBackupRunStatus.PENDING, ScheduledBackupRunStatus.WAITING_FOR_DISK]
                )
            )
        )
    )
    for run in runs:
        event = db.get(ScheduledBackupEvent, run.event_id)
        if event is None or event.deleted_at is not None or not _disk_matches_event_serial(disk, event.disk_serial):
            continue
        if not (run.window_starts_at <= current_time <= run.window_ends_at):
            continue
        if run.disk_seen_at is None:
            run.disk_seen_at = current_time
            notify_expected_disk_detected(event.disk_serial, event.title)
        _advance_detected_run(db, event, run, current_time)
    db.commit()


def confirm_planning_run(db: Session, run_id: int) -> ScheduledBackupRun:
    run = _get_run_or_raise(db, run_id)
    event = db.get(ScheduledBackupEvent, run.event_id)
    if event is None:
        raise ValueError("Scheduled event not found.")
    now = datetime.utcnow()
    if run.status != ScheduledBackupRunStatus.WAITING_FOR_CONFIRMATION:
        raise ValueError("Run is not waiting for confirmation.")
    if now > run.window_ends_at:
        run.status = ScheduledBackupRunStatus.CANCELLED
        run.finished_at = now
        run.error = "Confirmation arrived after the planned window."
        db.add(run)
        db.commit()
        db.refresh(run)
        return run
    _start_run(db, event, run, now, notify_auto_start=False)
    db.commit()
    db.refresh(run)
    return run


def cancel_planning_run(db: Session, run_id: int) -> ScheduledBackupRun:
    run = _get_run_or_raise(db, run_id)
    if run.status in {ScheduledBackupRunStatus.SUCCESS, ScheduledBackupRunStatus.FAILURE, ScheduledBackupRunStatus.CANCELLED}:
        return run
    now = datetime.utcnow()
    run.status = ScheduledBackupRunStatus.CANCELLED
    run.finished_at = now
    run.updated_at = now
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def run_event_now(db: Session, event_id: int) -> ScheduledBackupRun:
    event = db.get(ScheduledBackupEvent, event_id)
    if event is None or event.deleted_at is not None:
        raise ValueError("Scheduled event not found.")
    now = datetime.utcnow()
    run = ScheduledBackupRun(
        event_id=event.id,
        scheduled_for=now,
        window_starts_at=now,
        window_ends_at=now + timedelta(minutes=event.window_duration_minutes),
        status=ScheduledBackupRunStatus.PENDING,
        created_at=now,
        updated_at=now,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    _start_run(db, event, run, now, notify_auto_start=False)
    db.commit()
    db.refresh(run)
    return run


def next_occurrence(event: ScheduledBackupEvent, after: datetime) -> datetime | None:
    return next(iter(expand_occurrences(event, after, after + timedelta(days=370))), None)


def expand_occurrences(event: ScheduledBackupEvent, range_start: datetime, range_end: datetime) -> list[datetime]:
    if event.deleted_at is not None:
        return []
    start = event.window_starts_at
    occurrences: list[datetime] = []
    if event.recurrence_type == ScheduledBackupRecurrenceType.ONCE:
        occurrences = [start] if range_start <= start <= range_end else []
    elif event.recurrence_type == ScheduledBackupRecurrenceType.DAILY:
        days = max(0, (range_start.date() - start.date()).days)
        candidate = start + timedelta(days=days)
        if candidate < range_start:
            candidate += timedelta(days=1)
        while candidate <= range_end:
            occurrences.append(candidate)
            candidate += timedelta(days=1)
    elif event.recurrence_type == ScheduledBackupRecurrenceType.WEEKLY:
        weeks = max(0, (range_start.date() - start.date()).days // 7)
        candidate = start + timedelta(weeks=weeks)
        while candidate < range_start:
            candidate += timedelta(weeks=1)
        while candidate <= range_end:
            occurrences.append(candidate)
            candidate += timedelta(weeks=1)
    elif event.recurrence_type == ScheduledBackupRecurrenceType.MONTHLY:
        candidate = start
        while candidate < range_start:
            year = candidate.year + (1 if candidate.month == 12 else 0)
            month = 1 if candidate.month == 12 else candidate.month + 1
            day = min(start.day, _days_in_month(year, month))
            candidate = candidate.replace(year=year, month=month, day=day)
        while candidate <= range_end:
            occurrences.append(candidate)
            year = candidate.year + (1 if candidate.month == 12 else 0)
            month = 1 if candidate.month == 12 else candidate.month + 1
            day = min(start.day, _days_in_month(year, month))
            candidate = candidate.replace(year=year, month=month, day=day)
    logger.info(
        "planning occurrence expansion event_id=%s recurrence=%s count=%s range_start=%s range_end=%s",
        event.id,
        event.recurrence_type.value,
        len(occurrences),
        range_start.isoformat(timespec="seconds"),
        range_end.isoformat(timespec="seconds"),
    )
    return occurrences


def _process_run(db: Session, event: ScheduledBackupEvent, run: ScheduledBackupRun, now: datetime) -> None:
    _sync_linked_backup_state(db, event, run, now)
    if run.status in {ScheduledBackupRunStatus.SUCCESS, ScheduledBackupRunStatus.FAILURE, ScheduledBackupRunStatus.CANCELLED}:
        return

    if run.reminder_sent_at is None and now >= run.window_starts_at - timedelta(minutes=event.notify_before_minutes):
        notify_planned_backup_reminder(
            event.disk_serial,
            event.title,
            run.window_starts_at.isoformat(timespec="minutes"),
            run.window_ends_at.isoformat(timespec="minutes"),
        )
        run.reminder_sent_at = now

    if now > run.window_ends_at and _can_mark_missed(run):
        run.status = ScheduledBackupRunStatus.MISSED
        run.finished_at = now
        run.error = "Planned window expired."
        event.last_status = run.status.value
        event.last_completed_at = now
        notify_planned_backup_missed(event.title)
        db.add_all([event, run])
        return
    if now > run.window_ends_at:
        run.updated_at = now
        db.add(run)
        return

    if now < run.window_starts_at:
        db.add(run)
        return

    disk = _get_present_disk(db, event.disk_serial)
    if disk is None:
        if run.status == ScheduledBackupRunStatus.PENDING:
            run.status = ScheduledBackupRunStatus.WAITING_FOR_DISK
        db.add(run)
        return

    if run.disk_seen_at is None:
        run.disk_seen_at = now
        notify_expected_disk_detected(event.disk_serial, event.title)
    _advance_detected_run(db, event, run, now)


def _advance_detected_run(db: Session, event: ScheduledBackupEvent, run: ScheduledBackupRun, now: datetime) -> None:
    if run.backup_run_id is not None:
        return
    if event.start_mode == ScheduledBackupStartMode.MANUAL_CONFIRMATION:
        if run.status != ScheduledBackupRunStatus.WAITING_FOR_CONFIRMATION:
            run.status = ScheduledBackupRunStatus.WAITING_FOR_CONFIRMATION
            notify_planned_confirmation_required(event.title)
        run.updated_at = now
        db.add(run)
        return
    _start_run(db, event, run, now, notify_auto_start=True)


def _start_run(
    db: Session,
    event: ScheduledBackupEvent,
    run: ScheduledBackupRun,
    now: datetime,
    *,
    notify_auto_start: bool,
) -> None:
    if _external_backup_running(db):
        run.error = "Another external backup is already running."
        run.status = ScheduledBackupRunStatus.WAITING_FOR_EXTERNAL_BACKUP
        run.updated_at = now
        db.add(run)
        return
    disk = _get_present_disk(db, event.disk_serial) or _get_disk_by_serial_identity(db, event.disk_serial)
    if disk is None:
        run.status = ScheduledBackupRunStatus.WAITING_FOR_DISK
        run.updated_at = now
        db.add(run)
        return
    try:
        backup_run = run_external_backup(db, disk.id, confirmation=True, datastore_name=event.datastore)
    except Exception as exc:
        if getattr(exc, "status_code", None) == 409:
            run.status = ScheduledBackupRunStatus.WAITING_FOR_EXTERNAL_BACKUP
            run.error = "Another external backup is already running."
            run.updated_at = now
            db.add(run)
            return
        run.status = ScheduledBackupRunStatus.FAILURE
        run.finished_at = now
        run.error = str(exc)
        event.last_status = run.status.value
        event.last_completed_at = now
        notify_backup_failure(f"{event.disk_label_or_model or event.disk_serial} ({event.title})", "planning_start", str(exc))
        db.add_all([event, run])
        return

    run.status = ScheduledBackupRunStatus.RUNNING
    run.backup_run_id = backup_run.id
    run.started_at = now
    run.updated_at = now
    event.last_status = run.status.value
    event.last_triggered_at = now
    db.add_all([event, run])
    db.commit()
    if notify_auto_start:
        notify_planned_backup_started(event.title)
    thread = threading.Thread(target=execute_external_backup_run, args=(backup_run.id,), daemon=True)
    thread.start()


def _sync_linked_backup_state(db: Session, event: ScheduledBackupEvent, run: ScheduledBackupRun, now: datetime) -> None:
    if run.backup_run_id is None or run.status != ScheduledBackupRunStatus.RUNNING:
        return
    backup_run = db.get(ExternalBackupRun, run.backup_run_id)
    if backup_run is None:
        return
    if backup_run.status in {BackupRunStatus.PENDING, BackupRunStatus.RUNNING}:
        run.status = ScheduledBackupRunStatus.RUNNING
        run.updated_at = now
        db.add(run)
        return
    run.status = ScheduledBackupRunStatus.SUCCESS if backup_run.status == BackupRunStatus.SUCCESS else ScheduledBackupRunStatus.FAILURE
    run.finished_at = backup_run.finished_at or now
    run.error = backup_run.message if run.status == ScheduledBackupRunStatus.FAILURE else None
    event.last_status = run.status.value
    event.last_completed_at = run.finished_at
    db.add_all([event, run])
    if run.status == ScheduledBackupRunStatus.SUCCESS and event.auto_eject_after_success:
        disk = _get_disk_by_serial_identity(db, event.disk_serial)
        if disk is not None:
            try:
                eject_dedicated_external_disk(db, disk.id)
            except Exception as exc:
                logger.warning("planned auto-eject failed for event_id=%s: %s", event.id, exc)


def _ensure_run(db: Session, event: ScheduledBackupEvent, occurrence: datetime) -> ScheduledBackupRun:
    existing = db.scalar(
        select(ScheduledBackupRun)
        .where(
            ScheduledBackupRun.event_id == event.id,
            ScheduledBackupRun.scheduled_for == occurrence,
        )
        .limit(1)
    )
    if existing is not None:
        return existing
    now = datetime.utcnow()
    run = ScheduledBackupRun(
        event_id=event.id,
        scheduled_for=occurrence,
        window_starts_at=occurrence,
        window_ends_at=occurrence + timedelta(minutes=event.window_duration_minutes),
        status=ScheduledBackupRunStatus.PENDING,
        created_at=now,
        updated_at=now,
    )
    db.add(run)
    return run


def _get_present_disk(db: Session, serial: str) -> ExternalDisk | None:
    for disk in db.scalars(select(ExternalDisk).where(ExternalDisk.presence_state == "present")):
        if _disk_matches_event_serial(disk, serial):
            return disk
    return None


def _get_disk_by_serial_identity(db: Session, serial: str) -> ExternalDisk | None:
    exact = db.scalar(select(ExternalDisk).where(ExternalDisk.serial_number == serial).limit(1))
    if exact is not None:
        return exact
    for disk in db.scalars(select(ExternalDisk)):
        if _disk_matches_event_serial(disk, serial):
            return disk
    return None


def _disk_matches_event_serial(disk: ExternalDisk, event_serial: str) -> bool:
    if serials_match(disk.serial_number, event_serial):
        return True
    if disk.reported_serial_number and serials_match(disk.reported_serial_number, event_serial):
        return True
    event_aliases = set(serial_aliases(event_serial))
    disk_aliases = set(disk.serial_aliases or [])
    if disk.canonical_serial_number:
        disk_aliases.add(disk.canonical_serial_number)
    return bool(event_aliases & disk_aliases)


def _external_backup_running(db: Session) -> bool:
    return bool(
        db.scalar(
            select(ExternalBackupRun.id)
            .where(ExternalBackupRun.status.in_([BackupRunStatus.PENDING, BackupRunStatus.RUNNING]))
            .limit(1)
        )
    )


def _can_mark_missed(run: ScheduledBackupRun) -> bool:
    return (
        run.disk_seen_at is None
        and run.backup_run_id is None
        and run.started_at is None
        and run.status
        in {
            ScheduledBackupRunStatus.PENDING,
            ScheduledBackupRunStatus.WAITING_FOR_DISK,
        }
    )


def _get_run_or_raise(db: Session, run_id: int) -> ScheduledBackupRun:
    run = db.get(ScheduledBackupRun, run_id)
    if run is None:
        raise ValueError("Scheduled run not found.")
    return run


def _scheduler_loop(interval_seconds: int) -> None:
    while not _scheduler_stop.wait(max(5, interval_seconds)):
        try:
            scheduler_tick()
        except Exception as exc:
            logger.warning("planning scheduler tick failed: %s", exc)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        next_month = datetime(year + 1, 1, 1)
    else:
        next_month = datetime(year, month + 1, 1)
    return (next_month - timedelta(days=1)).day
