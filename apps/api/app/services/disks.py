from datetime import datetime, timedelta

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import AgentHeartbeat, ExternalDisk
from app.schemas.agent import AgentDiskReportCreate, AgentHeartbeatCreate


def has_agent_disks(db: Session) -> bool:
    statement = select(
        exists().where(
            ExternalDisk.source == "agent",
            ExternalDisk.active.is_(True),
        )
    )
    return bool(db.scalar(statement))


def list_preferred_disks(db: Session) -> list[ExternalDisk]:
    statement = select(ExternalDisk).where(ExternalDisk.active.is_(True))
    if has_agent_disks(db):
        statement = statement.where(ExternalDisk.source == "agent")

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
            dedicated_backup_disk=False,
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
                dedicated_backup_disk=False,
                allow_existing_data=False,
                source="agent",
                active=True,
                trusted=item.trusted,
            )

        disk.display_name = item.display_name
        disk.model_name = item.model_name
        disk.capacity_gb = item.capacity_gb
        disk.filesystem_type = item.filesystem_type
        disk.mount_path = item.mount_path
        disk.detection_reason = item.detection_reason
        disk.candidate_type = item.candidate_type
        disk.connected = item.connected
        disk.last_seen_at = observed_at
        disk.source = "agent"
        disk.reported_by_hostname = payload.hostname
        disk.active = True

        db.add(disk)
        upserted.append(disk)

    for disk in stale_disks:
        if disk.serial_number in reported_serials:
            continue

        disk.connected = False
        disk.active = False
        disk.reported_by_hostname = payload.hostname
        db.add(disk)

    db.commit()

    for disk in upserted:
        db.refresh(disk)

    return upserted


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
