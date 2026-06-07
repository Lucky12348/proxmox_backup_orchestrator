import logging
from datetime import datetime, timedelta

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import AgentHeartbeat, ExternalDisk, ScheduledBackupEvent
from app.schemas.agent import AgentDiskReportCreate, AgentHeartbeatCreate
from app.services.disk_identity import canonical_serial_number, serial_aliases, serials_match
from app.services.notifications import (
    get_disk_detection_notify_cooldown_seconds,
    notify_known_disk_detected,
    notify_new_disk_detected,
)
from app.services.planning_scheduler import handle_disk_detected


logger = logging.getLogger(__name__)
ZERO_SIZE_DISK_MESSAGE = "Disque détecté mais taille 0B — port/câble/initialisation USB probablement défaillant."


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
    reported_aliases = {alias for item in payload.disks for alias in serial_aliases(item.serial_number)}
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
        incoming_canonical = canonical_serial_number(item.serial_number)
        incoming_aliases = serial_aliases(item.serial_number)
        disk = _find_existing_disk_by_serial_identity(db, item.serial_number)
        unusable_zero_size = item.capacity_gb <= 0

        if disk is None:
            disk = ExternalDisk(
                serial_number=incoming_canonical or item.serial_number,
                dedicated_backup_disk=True,
                allow_existing_data=False,
                source="agent",
                active=True,
                trusted=item.trusted,
            )
            if unusable_zero_size:
                disk.dedicated_backup_disk = False
                disk.trusted = False
            previous_presence = "never_seen"
            is_new_disk = True
            logger.debug("disk classified as new because serial %s canonical %s was not found", item.serial_number, incoming_canonical)
        else:
            previous_presence = disk.presence_state or ("present" if disk.connected else "absent")
            is_new_disk = False
            logger.debug(
                "disk classified as known because serial %s canonical %s matched disk id %s",
                item.serial_number,
                incoming_canonical,
                disk.id,
            )

        previous_serial = disk.serial_number
        disk.reported_serial_number = item.serial_number
        disk.reported_display_name = item.display_name
        disk.reported_model_name = item.model_name
        disk.reported_mount_path = item.mount_path
        disk.canonical_serial_number = incoming_canonical or disk.canonical_serial_number
        disk.serial_aliases = _merge_aliases(disk.serial_aliases, [*incoming_aliases, *serial_aliases(previous_serial)])
        if is_new_disk and (not disk.serial_number or serials_match(disk.serial_number, item.serial_number)):
            disk.serial_number = disk.canonical_serial_number or disk.serial_number or item.serial_number
        disk.display_name = _reconcile_display_name(disk.display_name, item.display_name)
        disk.model_name = _reconcile_model_name(disk.model_name, item.model_name)
        disk.capacity_gb = item.capacity_gb
        disk.filesystem_type = _reconcile_filesystem_type(disk, item)
        disk.mount_path = _reconcile_mount_path(disk, item)
        disk.filesystem_total_gb = item.filesystem_total_gb
        disk.filesystem_used_gb = item.filesystem_used_gb
        disk.filesystem_free_gb = item.filesystem_free_gb
        disk.detection_reason = ZERO_SIZE_DISK_MESSAGE if unusable_zero_size else item.detection_reason
        disk.candidate_type = "unusable" if unusable_zero_size else item.candidate_type
        if unusable_zero_size:
            disk.trusted = False
            disk.dedicated_backup_disk = False
            disk.allow_existing_data = False
        disk.connected = True if _is_pbs_handoff_disk(disk) else item.connected
        disk.presence_state = "present" if disk.connected else "absent"
        disk.last_seen_at = observed_at
        disk.source = "agent"
        disk.reported_by_hostname = payload.hostname
        disk.active = True

        db.add(disk)
        upserted.append(disk)
        if disk.connected and previous_presence in {"never_seen", "absent"} and not _is_unusable_disk(disk):
            planning_detections.append(disk)
            if _disk_detection_cooldown_elapsed(disk, observed_at):
                detection_notifications.append(("new" if previous_presence == "never_seen" else "known", disk))
                disk.last_detection_notified_at = observed_at

    for disk in stale_disks:
        existing_aliases = set(serial_aliases(disk.serial_number)) | set(disk.serial_aliases or [])
        if existing_aliases & reported_aliases:
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
                any(_disk_matches_event_serial(disk, event.disk_serial) for event in db.scalars(select(ScheduledBackupEvent)))
            )
            description = _format_disk_detection_description(
                disk,
                matched_planned_disk=matched_planned_disk,
                matched_existing_serial=disk.serial_number,
            )
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


def _find_existing_disk_by_serial_identity(db: Session, reported_serial: str) -> ExternalDisk | None:
    exact = db.scalar(
        select(ExternalDisk)
        .where(
            or_(
                ExternalDisk.serial_number == reported_serial,
                ExternalDisk.reported_serial_number == reported_serial,
            )
        )
        .limit(1)
    )
    if exact is not None:
        return exact

    canonical = canonical_serial_number(reported_serial)
    if canonical:
        by_canonical = db.scalar(
            select(ExternalDisk)
            .where(ExternalDisk.canonical_serial_number == canonical)
            .limit(1)
        )
        if by_canonical is not None:
            return by_canonical

    incoming_aliases = set(serial_aliases(reported_serial))
    for disk in db.scalars(select(ExternalDisk).where(ExternalDisk.serial_number.not_like("agent-report::%"))):
        existing_aliases = set(serial_aliases(disk.serial_number))
        if disk.reported_serial_number:
            existing_aliases.update(serial_aliases(disk.reported_serial_number))
        if disk.canonical_serial_number:
            existing_aliases.add(disk.canonical_serial_number)
        existing_aliases.update(disk.serial_aliases or [])
        if incoming_aliases & existing_aliases:
            return disk
    return None


def _reconcile_mount_path(disk: ExternalDisk, item) -> str | None:
    incoming = _normalize_optional_string(item.mount_path)
    existing = _normalize_optional_string(disk.mount_path)
    if incoming:
        return incoming
    if existing:
        return existing
    return incoming


def _reconcile_display_name(existing: str | None, incoming: str | None) -> str:
    existing_clean = _normalize_optional_string(existing)
    incoming_clean = _normalize_optional_string(incoming)
    if not existing_clean:
        return incoming_clean or "External disk"
    if not incoming_clean:
        return existing_clean
    if _is_bridge_name(incoming_clean) and not _is_bridge_name(existing_clean):
        return existing_clean
    return existing_clean


def _reconcile_model_name(existing: str | None, incoming: str | None) -> str | None:
    existing_clean = _normalize_optional_string(existing)
    incoming_clean = _normalize_optional_string(incoming)
    if not existing_clean:
        return incoming_clean
    if not incoming_clean:
        return existing_clean
    if _is_bridge_name(incoming_clean) and not _is_bridge_name(existing_clean):
        return existing_clean
    return existing_clean


def _is_bridge_name(value: str) -> bool:
    clean = value.strip().casefold()
    return clean in {"game drive", "external usb", "usb disk", "usb storage", "mass storage"}


def _merge_aliases(existing: list[str] | None, incoming: list[str]) -> list[str]:
    merged: list[str] = []
    for value in [*(existing or []), *incoming]:
        if value and value not in merged:
            merged.append(value)
    return merged


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


def _format_disk_detection_description(
    disk: ExternalDisk,
    *,
    matched_planned_disk: bool = False,
    matched_existing_serial: str | None = None,
) -> str:
    parts = [f"Disque: {disk.display_name}"]
    if disk.model_name:
        parts.append(f"Modele: {disk.model_name}")
    if disk.reported_serial_number:
        parts.append(f"Serie reportee: {disk.reported_serial_number}")
    parts.append(f"Serie canonique: {disk.canonical_serial_number or canonical_serial_number(disk.serial_number)}")
    if matched_existing_serial:
        parts.append(f"Serie existante: {matched_existing_serial}")
    if disk.mount_path:
        parts.append(f"Chemin: {disk.mount_path}")
    if disk.proxmox_usb_mapping:
        parts.append(f"USB: {disk.proxmox_usb_mapping}")
    if disk.detection_reason:
        parts.append(f"Detection: {disk.detection_reason}")
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


def _is_unusable_disk(disk: ExternalDisk) -> bool:
    return disk.capacity_gb <= 0 or disk.candidate_type == "unusable"


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
