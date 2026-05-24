from datetime import datetime, timezone

from fastapi import APIRouter

from app.schemas.maintenance import (
    MaintenanceActionRead,
    MaintenanceCommandResultRead,
    MaintenanceComponentStatusRead,
    MaintenanceStatusRead,
)
from app.services.maintenance import (
    MaintenanceActionResult,
    MaintenanceCommandResult,
    MaintenanceComponentStatus,
    check_agent_status,
    check_all_status,
    check_app_status,
    get_maintenance_host_agent_client,
    get_maintenance_pbs_agent_client,
    update_agent,
    update_all,
    update_app,
)
from app.services.notifications import notify_update_result


router = APIRouter(prefix="/maintenance/updates", tags=["maintenance"])


@router.get("/status", response_model=MaintenanceStatusRead)
def get_update_status() -> MaintenanceStatusRead:
    return MaintenanceStatusRead(components=[_status_read(item) for item in check_all_status()])


@router.post("/app/check", response_model=MaintenanceComponentStatusRead)
def check_app_updates() -> MaintenanceComponentStatusRead:
    return _status_read(check_app_status())


@router.post("/app/update", response_model=MaintenanceActionRead)
def update_app_vm() -> MaintenanceActionRead:
    return _action_read_with_notification(update_app())


@router.post("/proxmox-agent/check", response_model=MaintenanceComponentStatusRead)
def check_proxmox_agent_updates() -> MaintenanceComponentStatusRead:
    return _status_read(check_agent_status("proxmox-agent", get_maintenance_host_agent_client()))


@router.post("/proxmox-agent/update", response_model=MaintenanceActionRead)
def update_proxmox_agent() -> MaintenanceActionRead:
    return _action_read_with_notification(update_agent("proxmox-agent", get_maintenance_host_agent_client()))


@router.post("/pbs-agent/check", response_model=MaintenanceComponentStatusRead)
def check_pbs_agent_updates() -> MaintenanceComponentStatusRead:
    return _status_read(check_agent_status("pbs-agent", get_maintenance_pbs_agent_client()))


@router.post("/pbs-agent/update", response_model=MaintenanceActionRead)
def update_pbs_agent() -> MaintenanceActionRead:
    return _action_read_with_notification(update_agent("pbs-agent", get_maintenance_pbs_agent_client()))


@router.post("/update-all", response_model=list[MaintenanceActionRead])
def update_all_components() -> list[MaintenanceActionRead]:
    return [_action_read_with_notification(item) for item in update_all()]


def _action_read_with_notification(result: MaintenanceActionResult) -> MaintenanceActionRead:
    read = _action_read(result)
    success = read.action_status != "error"
    notify_update_result(
        result.component,
        success,
        read.status.error or _first_error_log(read.logs),
    )
    return read


def _status_read(status: MaintenanceComponentStatus) -> MaintenanceComponentStatusRead:
    return MaintenanceComponentStatusRead(
        component=status.component,
        branch=status.branch,
        local_commit=status.local_commit,
        remote_commit=status.remote_commit,
        status=status.status,
        error=status.error,
        logs=[_command_read(item) for item in status.logs or []],
    )


def _action_read(result: MaintenanceActionResult) -> MaintenanceActionRead:
    action_status = result.action_status
    if action_status is None:
        action_status = "error" if result.status.status == "error" or any(item.return_code != 0 for item in result.logs) else "success"
    return MaintenanceActionRead(
        component=result.component,
        status=_status_read(result.status),
        logs=[_command_read(item) for item in result.logs],
        action_status=action_status,
        finished_at=datetime.now(timezone.utc),
    )


def _command_read(result: MaintenanceCommandResult) -> MaintenanceCommandResultRead:
    return MaintenanceCommandResultRead(
        command=result.command,
        stdout=result.stdout,
        stderr=result.stderr,
        return_code=result.return_code,
    )


def _first_error_log(logs: list[MaintenanceCommandResultRead]) -> str | None:
    for log in logs:
        if log.return_code != 0:
            return log.stderr or log.stdout or log.command
    return None
