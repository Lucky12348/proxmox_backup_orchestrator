from fastapi import APIRouter

from app.schemas.notifications import NotificationStatusRead, NotificationTestRead
from app.services.notifications import get_notification_service


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
    )


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
