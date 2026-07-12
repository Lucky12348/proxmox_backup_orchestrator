import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, status as http_status

from app.api.dependencies import DbSession
from app.core.config import get_settings
from app.schemas.agent import (
    AgentDiskReportCreate,
    AgentHeartbeatCreate,
    AgentHeartbeatRead,
    AgentStatusRead,
)
from app.services.disks import get_agent_status, ingest_agent_disk_report, record_agent_heartbeat
from app.services.notifications import notify_agent_degraded
from app.schemas.external_disk import ExternalDiskRead


router = APIRouter(prefix="/agent", tags=["agent"])
# Read by the authenticated web UI (dashboard status), unlike `router` above which is
# called by the host/PBS agents themselves and authenticated with X-Agent-Token instead.
status_router = APIRouter(prefix="/agent", tags=["agent"])


def require_reporting_agent_token(x_agent_token: str | None = Header(default=None)) -> None:
    """Authenticate calls made *by* the host or PBS agent (heartbeat/disk reports).

    Either shared secret is accepted since both agents report through the same
    endpoints, identified by their own `hostname` field in the payload.
    """
    settings = get_settings()
    configured_tokens = [token for token in (settings.host_agent_token, settings.pbs_agent_token) if token]
    if not configured_tokens:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Neither HOST_AGENT_TOKEN nor PBS_AGENT_TOKEN is configured.",
        )
    if x_agent_token is None or not any(
        secrets.compare_digest(x_agent_token, token) for token in configured_tokens
    ):
        raise HTTPException(status_code=http_status.HTTP_401_UNAUTHORIZED, detail="Invalid agent token.")


@router.post(
    "/heartbeat",
    response_model=AgentHeartbeatRead,
    dependencies=[Depends(require_reporting_agent_token)],
)
def post_heartbeat(payload: AgentHeartbeatCreate, db: DbSession) -> AgentHeartbeatRead:
    heartbeat = record_agent_heartbeat(db, payload)
    return AgentHeartbeatRead.model_validate(heartbeat)


@router.post(
    "/disks/report",
    response_model=list[ExternalDiskRead],
    dependencies=[Depends(require_reporting_agent_token)],
)
def post_disk_report(payload: AgentDiskReportCreate, db: DbSession) -> list[ExternalDiskRead]:
    disks = ingest_agent_disk_report(db, payload)
    return [ExternalDiskRead.model_validate(disk) for disk in disks]


@status_router.get("/status", response_model=AgentStatusRead)
def get_status(db: DbSession) -> AgentStatusRead:
    status = get_agent_status(db)
    notify_agent_degraded(status)
    return AgentStatusRead(**status)
