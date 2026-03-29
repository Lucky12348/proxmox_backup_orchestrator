from fastapi import APIRouter

from app.api.dependencies import DbSession
from app.schemas.agent import (
    AgentDiskReportCreate,
    AgentHeartbeatCreate,
    AgentHeartbeatRead,
    AgentStatusRead,
)
from app.services.disks import get_agent_status, ingest_agent_disk_report, record_agent_heartbeat
from app.schemas.external_disk import ExternalDiskRead


router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/heartbeat", response_model=AgentHeartbeatRead)
def post_heartbeat(payload: AgentHeartbeatCreate, db: DbSession) -> AgentHeartbeatRead:
    heartbeat = record_agent_heartbeat(db, payload)
    return AgentHeartbeatRead.model_validate(heartbeat)


@router.post("/disks/report", response_model=list[ExternalDiskRead])
def post_disk_report(payload: AgentDiskReportCreate, db: DbSession) -> list[ExternalDiskRead]:
    disks = ingest_agent_disk_report(db, payload)
    return [ExternalDiskRead.model_validate(disk) for disk in disks]


@router.get("/status", response_model=AgentStatusRead)
def get_status(db: DbSession) -> AgentStatusRead:
    return AgentStatusRead(**get_agent_status(db))
