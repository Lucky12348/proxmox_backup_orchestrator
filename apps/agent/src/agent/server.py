import logging
import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agent.main import (
    AgentSettings,
    build_command_failure_payload,
    current_timestamp,
    prepare_disk_result,
    prepare_external_datastore_result,
    run_external_export_result,
)


logger = logging.getLogger("agent.server")
SERVER_STARTED_AT = datetime.now(timezone.utc).isoformat()

app = FastAPI(title="Proxmox Backup Orchestrator Agent", version="0.1.0")


class PrepareDiskRequest(BaseModel):
    disk: str = Field(min_length=1)
    mode: str
    mount_base_path: str | None = Field(default=None, max_length=255)
    confirm_destructive: bool = False


class PrepareExternalDatastoreRequest(BaseModel):
    mount_path: str = Field(min_length=1)
    target_path: str = Field(min_length=1)
    mode: str


class RunExternalExportRequest(BaseModel):
    target_path: str = Field(min_length=1)
    datastore_name: str = Field(min_length=1)
    mode: str


def get_settings() -> AgentSettings:
    return AgentSettings()


def require_agent_token(
    x_agent_token: str | None = Header(default=None),
    settings: AgentSettings = Depends(get_settings),
) -> None:
    expected = settings.server_token
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AGENT_SERVER_TOKEN is not configured on the host agent.",
        )
    if x_agent_token is None or not secrets.compare_digest(x_agent_token, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid agent token.")


@app.get("/health")
def health(_: None = Depends(require_agent_token), settings: AgentSettings = Depends(get_settings)) -> dict[str, Any]:
    return {
        "ok": True,
        "hostname": settings.hostname,
        "agent_version": settings.agent_version,
        "observed_at": current_timestamp(),
        "server_started_at": SERVER_STARTED_AT,
    }


@app.post("/prepare-disk", response_model=None)
def prepare_disk(
    payload: PrepareDiskRequest,
    _: None = Depends(require_agent_token),
) -> Response:
    return _run_endpoint(
        "prepare-disk",
        lambda: prepare_disk_result(
            payload.disk,
            payload.mode,
            payload.mount_base_path,
            payload.confirm_destructive,
        ),
    )


@app.post("/prepare-external-datastore", response_model=None)
def prepare_external_datastore(
    payload: PrepareExternalDatastoreRequest,
    _: None = Depends(require_agent_token),
) -> Response:
    return _run_endpoint(
        "prepare-external-datastore",
        lambda: prepare_external_datastore_result(payload.mount_path, payload.target_path, payload.mode),
    )


@app.post("/run-external-export", response_model=None)
def run_external_export(
    payload: RunExternalExportRequest,
    _: None = Depends(require_agent_token),
    settings: AgentSettings = Depends(get_settings),
) -> Response:
    return _run_endpoint(
        "run-external-export",
        lambda: run_external_export_result(payload.target_path, payload.datastore_name, payload.mode, settings),
    )


def _run_endpoint(command_name: str, action) -> Response:
    try:
        return JSONResponse(content=action())
    except Exception as exc:
        logger.exception("Agent HTTP command %s failed", command_name)
        return JSONResponse(status_code=500, content=build_command_failure_payload(command_name, exc))
