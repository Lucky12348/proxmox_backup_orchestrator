import logging
from datetime import datetime, timedelta

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import AgentHeartbeat, ExternalDisk, ScheduledBackupEvent
from app.schemas.agent import AgentDiskReportCreate, AgentHeartbeatCreate
from app.services.notifications import (
    get_disk_detection_notify_cooldown_seconds,
    notify_known_disk_detected,
    notify_new_disk_detected,
)
from app.services.planning_scheduler import handle_disk_detected


logger = logging.getLogger(__name__)


def has_agent_disks(db: Session) -> bool:
    statement = select(
        exists().where(
            ExternalDisk.source == "agent",
            ExternalDisk.serial_number.not_like("agent-report::%"),
            _preferred_disk_visibility_condition(),
        )
    )
    return bool(db.scalar(statement))


def list_preferred_disks(db: Session) -> list[ExternalDisk]:
    settings = get_settings()
    visibility_condition = _preferred_disk_visibility_condition()
    if settings.show_seed_disks:
        visibility_condition = or_(
            visibility_condition,
            and_(ExternalDisk.source == "seed", ExternalDisk.active.is_(True)),
        )
    statement = select(ExternalDisk).where(
        visibility_condition,
        ExternalDisk.serial_number.not_like("agent-report::%"),
    )
    if not settings.show_seed_disks:
        statement = statement.where(ExternalDisk.source != "seed")
    elif has_agent_disks(db):
        statement = statement.where(
            or_(
                ExternalDisk.source == "seed",
                ExternalDisk.source == "agent",
            )
        )

    return list(
        db.scalars(
            statement.order_by(
                ExternalDisk.trusted.desc(),
                ExternalDisk.connected.desc(),
                ExternalDisk.display_name.asc(),
            )
        )
    )


def record_agent_heartbeat(db: Session, payload: AgentHeartbeatCreate) -> AgentHeartbeat:
    heartbeat = AgentHeartbeat(
        hostname=payload.hostname,
        agent_version=payload.agent_version,
        observed_at=payload.observed_at.replace(tzinfo=None),
    )
    db.add(heartbeat)
    db.commit()
    db.refresh(heartbeat)
    return heartbeat


def ingest_agent_disk_report(db: Session, payload: AgentDiskReportCreate) -> list[ExternalDisk]:
    observed_at = payload.observed_at.replace(tzinfo=None)
    upserted: list[ExternalDisk] = []
    reported_serials = {item.serial_number for item in payload.disks}
    detection_notifications: list[tuple[str, ExternalDisk]] = []
    planning_detections: list[ExternalDisk] = []

    report_marker = db.scalar(
        select(ExternalDisk)
        .where(
            ExternalDisk.source == "agent",
            ExternalDisk.serial_number == f"agent-report::{payload.hostname}",
        )
    )
    if report_marker is None:
        report_marker = ExternalDisk(
            serial_number=f"agent-report::{payload.hostname}",
            display_name=f"Agent report marker {payload.hostname}",
            dedicated_backup_disk=True,
            allow_existing_data=False,
            source="agent",
            active=False,
            trusted=False,
        )
    report_marker.last_seen_at = observed_at
    report_marker.connected = False
    report_marker.reported_by_hostname = payload.hostname
    db.add(report_marker)

    stale_disks = list(
        db.scalars(
            select(ExternalDisk).where(
                ExternalDisk.source == "agent",
                ExternalDisk.active.is_(True),
                ExternalDisk.serial_number != f"agent-report::{payload.hostname}",
                or_(
                    ExternalDisk.reported_by_hostname == payload.hostname,
                    ExternalDisk.reported_by_hostname.is_(None),
                ),
            )
        )
    )

    for item in payload.disks:
        disk = db.scalar(
            select(ExternalDisk).where(ExternalDisk.serial_number == item.serial_number)
        )

        if disk is None:
            disk = ExternalDisk(
                serial_number=item.serial_number,
                dedicated_backup_disk=True,
                allow_existing_data=False,
                source="agent",
                active=True,
                trusted=item.trusted,
            )
            previous_presence = "never_seen"
            logger.debug("disk classified as new because serial %s was not found", item.serial_number)
        else:
            previous_presence = disk.presence_state or ("present" if disk.connected else "absent")
            logger.debug("disk classified as known because serial %s matched disk id %s", item.serial_number, disk.id)

        disk.display_name = item.display_name
        disk.model_name = item.model_name
        disk.capacity_gb = item.capacity_gb
        disk.filesystem_type = _reconcile_filesystem_type(disk, item)
        disk.mount_path = _reconcile_mount_path(disk, item)
        disk.detection_reason = item.detection_reason
        disk.candidate_type = item.candidate_type
        disk.connected = True if _is_pbs_handoff_disk(disk) else item.connected
        disk.presence_state = "present" if disk.connected else "absent"
        disk.last_seen_at = observed_at
        disk.source = "agent"
        disk.reported_by_hostname = payload.hostname
        disk.active = True

        db.add(disk)
        upserted.append(disk)
        if disk.connected and previous_presence in {"never_seen", "absent"}:
            planning_detections.append(disk)
            if _disk_detection_cooldown_elapsed(disk, observed_at):
                detection_notifications.append(("new" if previous_presence == "never_seen" else "known", disk))
                disk.last_detection_notified_at = observed_at

    for disk in stale_disks:
        if disk.serial_number in reported_serials:
            continue

        if _is_pbs_handoff_disk(disk):
            disk.connected = True
            disk.presence_state = "present"
            disk.active = True
            disk.reported_by_hostname = payload.hostname
            disk.last_seen_at = observed_at
            db.add(disk)
            continue

        disk.connected = False
        disk.presence_state = "absent"
        disk.active = False
        disk.reported_by_hostname = payload.hostname
        db.add(disk)

    db.commit()

    for disk in upserted:
        db.refresh(disk)

    for detection_type, disk in detection_notifications:
        try:
            matched_planned_disk = bool(
                db.scalar(
                    select(exists().where(ScheduledBackupEvent.disk_serial == disk.serial_number))
                )
            )
            description = _format_disk_detection_description(disk, matched_planned_disk=matched_planned_disk)
            if detection_type == "new":
                notify_new_disk_detected(description)
            else:
                notify_known_disk_detected(description)
        except Exception:
            continue

    for disk in planning_detections:
        try:
            handle_disk_detected(db, disk, observed_at)
        except Exception:
            continue

    return upserted


def _reconcile_mount_path(disk: ExternalDisk, item) -> str | None:
    incoming = _normalize_optional_string(item.mount_path)
    existing = _normalize_optional_string(disk.mount_path)
    if incoming:
        return incoming
    if existing:
        return existing
    return incoming


def _reconcile_filesystem_type(disk: ExternalDisk, item) -> str | None:
    incoming = _normalize_optional_string(item.filesystem_type)
    existing = _normalize_optional_string(disk.filesystem_type)
    if incoming:
        return incoming
    if existing and item.connected:
        return existing
    return incoming


def _normalize_optional_string(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _is_pbs_handoff_disk(disk: ExternalDisk) -> bool:
    status = (disk.handoff_status or "").strip().casefold()
    return (
        status in {"attached_to_pbs", "visible_on_pbs"}
        or disk.pbs_visible is True
        or disk.pbs_handoff_slot is not None
    )


def _disk_detection_cooldown_elapsed(disk: ExternalDisk, observed_at: datetime) -> bool:
    previous = disk.last_detection_notified_at
    if previous is None:
        return True
    return (observed_at - previous).total_seconds() >= get_disk_detection_notify_cooldown_seconds()


def _format_disk_detection_description(disk: ExternalDisk, *, matched_planned_disk: bool = False) -> str:
    parts = []
    if disk.model_name:
        parts.append(f"Modele: {disk.model_name}")
    parts.append(f"Serie: {disk.serial_number}")
    if disk.mount_path:
        parts.append(f"Chemin: {disk.mount_path}")
    parts.append("Disque planifie: oui" if matched_planned_disk else "Disque planifie: non")
    capacity = disk.usable_capacity_gb or disk.capacity_gb
    if capacity:
        parts.append(f"Taille: {capacity} GB")
    return ". ".join(parts)


def _preferred_disk_visibility_condition():
    return or_(
        and_(ExternalDisk.source != "seed", ExternalDisk.active.is_(True)),
        and_(
            ExternalDisk.source != "seed",
            or_(
                ExternalDisk.trusted.is_(True),
                ExternalDisk.dedicated_backup_disk.is_(True),
                ExternalDisk.prepared_as_pbs_datastore.is_(True),
            ),
        ),
        ExternalDisk.pbs_visible.is_(True),
        ExternalDisk.pbs_handoff_slot.is_not(None),
        ExternalDisk.handoff_status.in_(["attached_to_pbs", "visible_on_pbs", "ejected"]),
    )


def get_agent_status(db: Session) -> dict[str, datetime | str | bool | int | None]:
    settings = get_settings()
    latest_heartbeat = db.scalar(
        select(AgentHeartbeat).order_by(AgentHeartbeat.observed_at.desc()).limit(1)
    )
    last_report_at = db.scalar(
        select(ExternalDisk.last_seen_at)
        .where(ExternalDisk.source == "agent")
        .order_by(ExternalDisk.last_seen_at.desc())
        .limit(1)
    )

    now = datetime.utcnow()
    latest_seen = latest_heartbeat.observed_at if latest_heartbeat else None
    stale_after = settings.agent_stale_after_minutes
    threshold = now - timedelta(minutes=stale_after)
    last_seen_age_seconds = None
    if latest_seen is not None:
        last_seen_age_seconds = max(0, int((now - latest_seen).total_seconds()))

    if latest_seen is None:
        status = "disconnected"
        connected = False
    elif latest_seen >= threshold:
        status = "connected"
        connected = True
    else:
        status = "degraded"
        connected = False

    return {
        "connected": connected,
        "hostname": latest_heartbeat.hostname if latest_heartbeat else None,
        "last_heartbeat_at": latest_seen,
        "last_report_at": last_report_at,
        "status": status,
        "stale_after_minutes": stale_after,
        "last_seen_age_seconds": last_seen_age_seconds,
    }
