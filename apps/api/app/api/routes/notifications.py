from fastapi import APIRouter

from app.api.dependencies import DbSession
from app.schemas.notifications import (
    NotificationPreferencesRead,
    NotificationPreferencesUpdate,
    NotificationStatusRead,
    NotificationTestRead,
)
from app.services.notifications import (
    get_notification_preferences,
    get_notification_service,
    reset_notification_preferences,
    update_notification_preferences,
)


router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("/status", response_model=NotificationStatusRead)
def get_notifications_status() -> NotificationStatusRead:
    status = get_notification_service().status()
    return NotificationStatusRead(
        enabled=status.enabled,
        provider=status.provider,
        configured=status.configured,
        base_url=status.base_url,
        topic=status.topic,
        username=status.username,
        events=status.events,
        low_coverage_threshold_percent=status.low_coverage_threshold_percent,
        environment_enabled=status.environment_enabled,
        preferences_enabled=status.preferences_enabled,
        disk_detection_notify_cooldown_seconds=status.disk_detection_notify_cooldown_seconds,
    )


@router.get("/preferences", response_model=NotificationPreferencesRead)
def get_preferences(db: DbSession) -> NotificationPreferencesRead:
    return _preferences_read(get_notification_preferences(db))


@router.patch("/preferences", response_model=NotificationPreferencesRead)
def patch_preferences(payload: NotificationPreferencesUpdate, db: DbSession) -> NotificationPreferencesRead:
    preferences = update_notification_preferences(db, payload.model_dump(exclude_unset=True))
    return _preferences_read(preferences)


@router.post("/preferences/reset", response_model=NotificationPreferencesRead)
def reset_preferences(db: DbSession) -> NotificationPreferencesRead:
    return _preferences_read(reset_notification_preferences(db))


@router.post("/test", response_model=NotificationTestRead)
def send_test_notification() -> NotificationTestRead:
    service = get_notification_service()
    sent = service.send(
        "PBO: Notification de test",
        "Notification de test envoyee depuis Proxmox Backup Orchestrator.",
        tags=["bell", "white_check_mark"],
    )
    return NotificationTestRead(
        sent=sent,
        message="Notification envoyee." if sent else "Notification non envoyee. Verifiez la configuration ntfy.",
    )


def _preferences_read(preferences) -> NotificationPreferencesRead:
    values = {
        "notifications_enabled_override": preferences.notifications_enabled_override,
        "low_coverage_threshold_percent": preferences.low_coverage_threshold_percent,
        "disk_detection_notify_cooldown_seconds": preferences.disk_detection_notify_cooldown_seconds,
        "updated_at": preferences.updated_at,
    }
    values.update(
        {
            "notify_on_backup_success": preferences.events["backup_success"],
            "notify_on_backup_failure": preferences.events["backup_failure"],
            "notify_on_disk_eject_ready": preferences.events["disk_eject_ready"],
            "notify_on_update_result": preferences.events["update_result"],
            "notify_on_agent_degraded": preferences.events["agent_degraded"],
            "notify_on_low_coverage": preferences.events["low_coverage"],
            "notify_on_disk_new_detected": preferences.events["disk_new_detected"],
            "notify_on_disk_known_detected": preferences.events["disk_known_detected"],
            "notify_on_planned_disk_detected": preferences.events["planned_disk_detected"],
            "notify_on_planned_backup_reminder": preferences.events["planned_backup_reminder"],
            "notify_on_planned_backup_started": preferences.events["planned_backup_started"],
            "notify_on_planned_confirmation_required": preferences.events["planned_confirmation_required"],
            "notify_on_planned_backup_missed": preferences.events["planned_backup_missed"],
        }
    )
    return NotificationPreferencesRead(**values)
