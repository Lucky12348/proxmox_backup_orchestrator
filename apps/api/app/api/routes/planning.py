import logging
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.dependencies import DbSession
from app.models import ScheduledBackupEvent, ScheduledBackupRun, ScheduledBackupRunStatus
from app.schemas import (
    DiskPlanningRead,
    PlanningOverviewRead,
    ScheduledBackupEventCreate,
    ScheduledBackupEventRead,
    ScheduledBackupEventUpdate,
    ScheduledBackupCalendarOccurrenceRead,
    ScheduledBackupRunRead,
    UnplannedAssetRead,
)
from app.services.planning import get_disk_planning, get_planning_overview, get_unplanned_assets
from app.services.planning_scheduler import (
    cancel_planning_run,
    confirm_planning_run,
    expand_occurrences,
    next_occurrence,
    run_event_now,
)


router = APIRouter(prefix="/planning", tags=["planning"])
logger = logging.getLogger(__name__)
ACTIVE_RUN_STATUSES = {
    ScheduledBackupRunStatus.PENDING,
    ScheduledBackupRunStatus.WAITING_FOR_DISK,
    ScheduledBackupRunStatus.WAITING_FOR_CONFIRMATION,
    ScheduledBackupRunStatus.RUNNING,
}


@router.get("/disks", response_model=list[DiskPlanningRead])
def get_planning_disks(db: DbSession) -> list[DiskPlanningRead]:
    return [DiskPlanningRead(**summary.__dict__) for summary in get_disk_planning(db)]


@router.get("/unplanned-assets", response_model=list[UnplannedAssetRead])
def get_unplanned(db: DbSession) -> list[UnplannedAssetRead]:
    return [
        UnplannedAssetRead(
            vm_id=vm.id,
            name=vm.name,
            vm_type=vm.vm_type,
            size_gb=vm.size_gb,
            critical=vm.critical,
        )
        for vm in get_unplanned_assets(db)
    ]


@router.get("/overview", response_model=PlanningOverviewRead)
def get_overview(db: DbSession) -> PlanningOverviewRead:
    return PlanningOverviewRead(**get_planning_overview(db).__dict__)


@router.get("/events", response_model=list[ScheduledBackupEventRead])
def list_events(db: DbSession) -> list[ScheduledBackupEventRead]:
    events = list(
        db.scalars(
            select(ScheduledBackupEvent)
            .where(ScheduledBackupEvent.deleted_at.is_(None))
            .order_by(ScheduledBackupEvent.window_starts_at.asc())
        )
    )
    return [_event_read(db, event) for event in events]


@router.get("/calendar", response_model=list[ScheduledBackupCalendarOccurrenceRead])
def get_calendar_occurrences(
    db: DbSession,
    start: date = Query(..., description="Visible range start date, inclusive"),
    end: date = Query(..., description="Visible range end date, inclusive"),
) -> list[ScheduledBackupCalendarOccurrenceRead]:
    if end < start:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="end must be on or after start")
    if (end - start).days > 370:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="calendar range cannot exceed 370 days")

    range_start = datetime.combine(start, time.min)
    range_end = datetime.combine(end, time.max)
    events = list(
        db.scalars(
            select(ScheduledBackupEvent)
            .where(ScheduledBackupEvent.deleted_at.is_(None))
            .order_by(ScheduledBackupEvent.window_starts_at.asc())
        )
    )
    runs = list(
        db.scalars(
            select(ScheduledBackupRun).where(
                ScheduledBackupRun.window_starts_at <= range_end,
                ScheduledBackupRun.window_ends_at >= range_start,
            )
        )
    )
    run_by_event_and_schedule = {(run.event_id, run.scheduled_for): run for run in runs}
    occurrences: list[ScheduledBackupCalendarOccurrenceRead] = []
    for event in events:
        if not event.enabled:
            continue
        for scheduled_for in expand_occurrences(event, range_start, range_end):
            run = run_by_event_and_schedule.get((event.id, scheduled_for))
            window_ends_at = scheduled_for + timedelta(minutes=event.window_duration_minutes)
            occurrences.append(
                ScheduledBackupCalendarOccurrenceRead(
                    event_id=event.id,
                    occurrence_id=f"{event.id}:{scheduled_for.isoformat()}",
                    scheduled_for=scheduled_for,
                    title=event.title,
                    disk_serial=event.disk_serial,
                    disk_label=event.disk_label_or_model,
                    window_starts_at=scheduled_for,
                    window_ends_at=window_ends_at,
                    status=run.status if run else None,
                    run_id=run.id if run else None,
                    start_mode=event.start_mode,
                    auto_eject_after_success=event.auto_eject_after_success,
                )
            )
    logger.info(
        "planning calendar expanded count=%s range_start=%s range_end=%s",
        len(occurrences),
        range_start.isoformat(timespec="seconds"),
        range_end.isoformat(timespec="seconds"),
    )
    return sorted(occurrences, key=lambda item: item.window_starts_at)


@router.post("/events", response_model=ScheduledBackupEventRead)
def create_event(payload: ScheduledBackupEventCreate, db: DbSession) -> ScheduledBackupEventRead:
    now = datetime.utcnow()
    event = ScheduledBackupEvent(
        **payload.model_dump(),
        created_at=now,
        updated_at=now,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return _event_read(db, event)


@router.get("/events/{event_id}", response_model=ScheduledBackupEventRead)
def get_event(event_id: int, db: DbSession) -> ScheduledBackupEventRead:
    event = db.get(ScheduledBackupEvent, event_id)
    if event is None or event.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scheduled event not found")
    return _event_read(db, event)


@router.patch("/events/{event_id}", response_model=ScheduledBackupEventRead)
def update_event(event_id: int, payload: ScheduledBackupEventUpdate, db: DbSession) -> ScheduledBackupEventRead:
    event = db.get(ScheduledBackupEvent, event_id)
    if event is None or event.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scheduled event not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(event, field, value)
    event.updated_at = datetime.utcnow()
    db.add(event)
    db.commit()
    db.refresh(event)
    return _event_read(db, event)


@router.delete("/events/{event_id}", status_code=204)
def delete_event(event_id: int, db: DbSession) -> None:
    event = db.get(ScheduledBackupEvent, event_id)
    if event is None or event.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scheduled event not found")
    active_run = db.scalar(
        select(ScheduledBackupRun.id)
        .where(
            ScheduledBackupRun.event_id == event.id,
            ScheduledBackupRun.status.in_(list(ACTIVE_RUN_STATUSES)),
        )
        .limit(1)
    )
    if active_run is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete event while a run is active. Cancel the run first.",
        )
    event.enabled = False
    event.deleted_at = datetime.utcnow()
    event.updated_at = event.deleted_at
    db.add(event)
    db.commit()
    logger.info("planning event soft-deleted event_id=%s", event.id)


@router.get("/runs", response_model=list[ScheduledBackupRunRead])
def list_runs(db: DbSession) -> list[ScheduledBackupRunRead]:
    runs = list(db.scalars(select(ScheduledBackupRun).order_by(ScheduledBackupRun.window_starts_at.desc()).limit(100)))
    return [_run_read(db, run) for run in runs]


@router.post("/events/{event_id}/run-now", response_model=ScheduledBackupRunRead)
def run_now(event_id: int, db: DbSession) -> ScheduledBackupRunRead:
    try:
        run = run_event_now(db, event_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _run_read(db, run)


@router.post("/runs/{run_id}/confirm", response_model=ScheduledBackupRunRead)
def confirm_run(run_id: int, db: DbSession) -> ScheduledBackupRunRead:
    try:
        run = confirm_planning_run(db, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _run_read(db, run)


@router.post("/runs/{run_id}/cancel", response_model=ScheduledBackupRunRead)
def cancel_run(run_id: int, db: DbSession) -> ScheduledBackupRunRead:
    try:
        run = cancel_planning_run(db, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _run_read(db, run)


def _event_read(db, event: ScheduledBackupEvent) -> ScheduledBackupEventRead:
    now = datetime.utcnow()
    active_run = db.scalar(
        select(ScheduledBackupRun)
        .where(
            ScheduledBackupRun.event_id == event.id,
            ScheduledBackupRun.status.in_(
                [
                    *ACTIVE_RUN_STATUSES,
                ]
            ),
        )
        .order_by(ScheduledBackupRun.window_starts_at.asc())
        .limit(1)
    )
    return ScheduledBackupEventRead(
        **{
            **event.__dict__,
            "next_occurrence_at": next_occurrence(event, now),
            "active_run": _run_read(db, active_run) if active_run is not None else None,
        }
    )


def _run_read(db, run: ScheduledBackupRun) -> ScheduledBackupRunRead:
    event = db.get(ScheduledBackupEvent, run.event_id)
    return ScheduledBackupRunRead(
        **{
            **run.__dict__,
            "event_title": event.title if event else None,
            "disk_serial": event.disk_serial if event else None,
        }
    )
