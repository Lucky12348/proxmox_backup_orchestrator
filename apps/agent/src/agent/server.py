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
    inspect_disk_result,
    prepare_disk_result,
    prepare_external_datastore_result,
    prepare_dedicated_pbs_datastore_result,
    cleanup_legacy_external_export_objects,
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
    callback_run_id: int | None = Field(default=None, gt=0)
    callback_url: str | None = Field(default=None, min_length=1)
    callback_token: str | None = Field(default=None, min_length=1)


class RunExternalExportRequest(BaseModel):
    target_path: str = Field(min_length=1)
    datastore_name: str = Field(min_length=1)
    mode: str
    callback_run_id: int | None = Field(default=None, gt=0)
    callback_url: str | None = Field(default=None, min_length=1)
    callback_token: str | None = Field(default=None, min_length=1)
    target_datastore_name: str | None = Field(default=None, min_length=1)
    persist_target_datastore: bool = False


class PrepareDedicatedPbsDatastoreRequest(BaseModel):
    disk: str = Field(min_length=1)
    datastore_name: str = Field(min_length=1)
    confirmation: bool = False
    callback_run_id: int | None = Field(default=None, gt=0)
    callback_url: str | None = Field(default=None, min_length=1)
    callback_token: str | None = Field(default=None, min_length=1)


class InspectDiskRequest(BaseModel):
    disk: str = Field(min_length=1)
    mount_base_path: str | None = Field(default=None, max_length=255)


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
    settings: AgentSettings = Depends(get_settings),
) -> Response:
    return _run_endpoint(
        "prepare-external-datastore",
        lambda: prepare_external_datastore_result(
            payload.mount_path,
            payload.target_path,
            payload.mode,
            settings,
            callback_run_id=payload.callback_run_id,
            callback_url=payload.callback_url,
            callback_token=payload.callback_token,
        ),
    )


@app.post("/prepare-dedicated-pbs-datastore", response_model=None)
def prepare_dedicated_pbs_datastore(
    payload: PrepareDedicatedPbsDatastoreRequest,
    _: None = Depends(require_agent_token),
    settings: AgentSettings = Depends(get_settings),
) -> Response:
    return _run_endpoint(
        "prepare-dedicated-pbs-datastore",
        lambda: prepare_dedicated_pbs_datastore_result(
            payload.disk,
            payload.datastore_name,
            payload.confirmation,
            settings,
            callback_run_id=payload.callback_run_id,
            callback_url=payload.callback_url,
            callback_token=payload.callback_token,
        ),
    )


@app.post("/inspect-disk", response_model=None)
def inspect_disk(
    payload: InspectDiskRequest,
    _: None = Depends(require_agent_token),
) -> Response:
    return _run_endpoint(
        "inspect-disk",
        lambda: inspect_disk_result(payload.disk, payload.mount_base_path),
    )


@app.post("/run-external-export", response_model=None)
def run_external_export(
    payload: RunExternalExportRequest,
    _: None = Depends(require_agent_token),
    settings: AgentSettings = Depends(get_settings),
) -> Response:
    return _run_endpoint(
        "run-external-export",
        lambda: run_external_export_result(
            payload.target_path,
            payload.datastore_name,
            payload.mode,
            settings,
            callback_run_id=payload.callback_run_id,
            callback_url=payload.callback_url,
            callback_token=payload.callback_token,
            target_datastore_name=payload.target_datastore_name,
            persist_target_datastore=payload.persist_target_datastore,
        ),
    )


@app.post("/cleanup-legacy-external-export-objects", response_model=None)
def cleanup_legacy_external_export(
    _: None = Depends(require_agent_token),
    settings: AgentSettings = Depends(get_settings),
) -> Response:
    return _run_endpoint(
        "cleanup-legacy-external-export-objects",
        lambda: cleanup_legacy_external_export_objects(settings),
    )


def _run_endpoint(command_name: str, action) -> Response:
    try:
        return JSONResponse(content=action())
    except Exception as exc:
        logger.exception("Agent HTTP command %s failed", command_name)
        return JSONResponse(status_code=500, content=build_command_failure_payload(command_name, exc))
