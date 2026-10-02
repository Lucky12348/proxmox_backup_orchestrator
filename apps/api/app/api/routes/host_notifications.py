from fastapi import APIRouter, Query

from app.api.dependencies import DbSession
from app.schemas.host_notifications import (
    EVENT_CODE_PATTERN,
    ActivityEventRead,
    HistoryStatus,
    HostNotificationHistoryRead,
    HostNotificationQueueRead,
    HostNotificationTemplates,
    HostNotificationTemplatesRead,
    HostNotificationTestRead,
    HostNotificationTestRequest,
)
from app.services import host_notifications


# Host-local ntfy engine on the Proxmox host (relayed through the host agent).
# Distinct from /notifications/* which configures the app's own ntfy sender.
router = APIRouter(prefix="/notifications/host", tags=["host-notifications"])
activity_router = APIRouter(prefix="/activity-events", tags=["activity"])


@router.get("/templates", response_model=HostNotificationTemplatesRead)
def get_templates() -> HostNotificationTemplatesRead:
    return HostNotificationTemplatesRead(**_pick(host_notifications.get_templates(), "path", "modified_at", "templates"))


@router.put("/templates", response_model=HostNotificationTemplatesRead)
def put_templates(payload: HostNotificationTemplates, db: DbSession) -> HostNotificationTemplatesRead:
    result = host_notifications.save_templates(db, payload)
    return HostNotificationTemplatesRead(**_pick(result, "path", "backup_path", "templates"))


@router.post("/test", response_model=HostNotificationTestRead)
def post_test(payload: HostNotificationTestRequest, db: DbSession) -> HostNotificationTestRead:
    result = host_notifications.send_test(db, payload)
    return HostNotificationTestRead(
        ok=bool(result.get("ok")),
        event=payload.event,
        return_code=result.get("return_code"),
        message=str(result.get("message") or ""),
        stdout_log=result.get("stdout_log"),
        stderr_log=result.get("stderr_log"),
    )


@router.get("/history", response_model=HostNotificationHistoryRead)
def get_history(
    limit: int = Query(default=200, ge=1, le=1000),
    event: str | None = Query(default=None, max_length=64, pattern=EVENT_CODE_PATTERN),
    status: HistoryStatus | None = Query(default=None),
) -> HostNotificationHistoryRead:
    result = host_notifications.get_history(limit, event, status)
    return HostNotificationHistoryRead(**_pick(result, "entries", "skipped_lines"))


@router.get("/queue", response_model=HostNotificationQueueRead)
def get_queue() -> HostNotificationQueueRead:
    return HostNotificationQueueRead(**_pick(host_notifications.get_queue(), "count", "oldest_ts", "oldest_age_seconds"))


@activity_router.get("", response_model=list[ActivityEventRead])
def list_activity_events(db: DbSession, limit: int = Query(default=100, ge=1, le=500)) -> list[ActivityEventRead]:
    return [ActivityEventRead.model_validate(item) for item in host_notifications.list_activity_events(db, limit)]


def _pick(payload: dict, *keys: str) -> dict:
    return {key: payload[key] for key in keys if key in payload}
