from datetime import datetime

from pydantic import BaseModel, Field

from app.models import ScheduledBackupRecurrenceType, ScheduledBackupRunStatus, ScheduledBackupStartMode, VMType
from app.schemas.base import UTCDateTimeModel


class DiskPlanningRead(BaseModel):
    disk_id: int
    serial_number: str
    display_name: str
    trusted: bool
    available_capacity_gb: int
    total_planned_gb: int
    planned_vm_count: int
    unplanned_vm_count: int
    fits_all: bool


class UnplannedAssetRead(BaseModel):
    vm_id: int
    name: str
    vm_type: VMType
    size_gb: int
    critical: bool


class PlanningOverviewRead(BaseModel):
    trusted_disk_count: int
    plannable_vm_count: int
    planned_vm_count: int
    planning_coverage_percent: float


class ScheduledBackupEventBase(BaseModel):
    title: str
    enabled: bool = True
    disk_serial: str
    disk_label_or_model: str | None = None
    datastore: str
    recurrence_type: ScheduledBackupRecurrenceType = ScheduledBackupRecurrenceType.WEEKLY
    recurrence_config: dict | None = None
    timezone: str = "Europe/Paris"
    window_starts_at: datetime
    window_duration_minutes: int = Field(default=300, ge=1)
    notify_before_minutes: int = Field(default=60, ge=0)
    start_mode: ScheduledBackupStartMode = ScheduledBackupStartMode.MANUAL_CONFIRMATION
    auto_eject_after_success: bool = False


class ScheduledBackupEventCreate(ScheduledBackupEventBase):
    pass


class ScheduledBackupEventUpdate(BaseModel):
    title: str | None = None
    enabled: bool | None = None
    disk_serial: str | None = None
    disk_label_or_model: str | None = None
    datastore: str | None = None
    recurrence_type: ScheduledBackupRecurrenceType | None = None
    recurrence_config: dict | None = None
    timezone: str | None = None
    window_starts_at: datetime | None = None
    window_duration_minutes: int | None = Field(default=None, ge=1)
    notify_before_minutes: int | None = Field(default=None, ge=0)
    start_mode: ScheduledBackupStartMode | None = None
    auto_eject_after_success: bool | None = None


class ScheduledBackupEventRead(UTCDateTimeModel, ScheduledBackupEventBase):
    id: int
    last_status: str | None = None
    last_triggered_at: datetime | None = None
    last_completed_at: datetime | None = None
    deleted_at: datetime | None = None
    next_occurrence_at: datetime | None = None
    active_run: "ScheduledBackupRunRead | None" = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ScheduledBackupRunRead(UTCDateTimeModel):
    id: int
    event_id: int
    event_title: str | None = None
    disk_serial: str | None = None
    scheduled_for: datetime
    window_starts_at: datetime
    window_ends_at: datetime
    status: ScheduledBackupRunStatus
    disk_seen_at: datetime | None = None
    reminder_sent_at: datetime | None = None
    backup_run_id: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ScheduledBackupCalendarOccurrenceRead(UTCDateTimeModel):
    event_id: int
    occurrence_id: str
    scheduled_for: datetime
    title: str
    disk_serial: str
    disk_label: str | None = None
    window_starts_at: datetime
    window_ends_at: datetime
    status: ScheduledBackupRunStatus | None = None
    run_id: int | None = None
    start_mode: ScheduledBackupStartMode
    auto_eject_after_success: bool
