from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.config import Settings, get_settings
from app.services.host_agent import HostAgentClient, HostAgentError


SECRET_PATTERNS = [
    re.compile(r"(?i)(token|secret|password|key)=([^\s]+)"),
    re.compile(r"(?i)(Authorization:\s*)([^\s]+)"),
]


@dataclass(frozen=True)
class MaintenanceCommandResult:
    command: str
    stdout: str | None
    stderr: str | None
    return_code: int


@dataclass(frozen=True)
class MaintenanceComponentStatus:
    component: str
    branch: str | None
    local_commit: str | None
    remote_commit: str | None
    status: str
    error: str | None = None
    logs: list[MaintenanceCommandResult] | None = None


@dataclass(frozen=True)
class MaintenanceActionResult:
    component: str
    status: MaintenanceComponentStatus
    logs: list[MaintenanceCommandResult]


def check_app_status(settings: Settings | None = None) -> MaintenanceComponentStatus:
    return check_agent_status("app-vm", get_app_maintenance_agent_client(settings))


def update_app(settings: Settings | None = None) -> MaintenanceActionResult:
    return update_agent("app-vm", get_app_maintenance_agent_client(settings))


def check_agent_status(component: str, client: HostAgentClient) -> MaintenanceComponentStatus:
    try:
        result = client.post("/maintenance/check", {})
    except HostAgentError as exc:
        return MaintenanceComponentStatus(
            component=component,
            branch=None,
            local_commit=None,
            remote_commit=None,
            status="error",
            error=str(exc),
            logs=[],
        )
    return _status_from_payload(component, result.payload)


def update_agent(component: str, client: HostAgentClient) -> MaintenanceActionResult:
    try:
        result = client.post("/maintenance/update", {})
    except HostAgentError as exc:
        status = MaintenanceComponentStatus(component, None, None, None, "error", str(exc), [])
        log = MaintenanceCommandResult(
            command=exc.command_summary or "agent maintenance update",
            stdout=exc.stdout_log,
            stderr=exc.stderr_log,
            return_code=exc.return_code or 1,
        )
        return MaintenanceActionResult(component, status, [log])
    status = _status_from_payload(component, result.payload.get("status", {}))
    logs = [_command_result_from_payload(item) for item in result.payload.get("logs", []) if isinstance(item, dict)]
    return MaintenanceActionResult(component, status, logs)


def check_all_status() -> list[MaintenanceComponentStatus]:
    return [
        check_app_status(),
        check_agent_status("proxmox-agent", get_maintenance_host_agent_client()),
        check_agent_status("pbs-agent", get_maintenance_pbs_agent_client()),
    ]


def update_all() -> list[MaintenanceActionResult]:
    return [
        update_agent("proxmox-agent", get_maintenance_host_agent_client()),
        update_agent("pbs-agent", get_maintenance_pbs_agent_client()),
        update_app(),
    ]


def get_app_maintenance_agent_client(settings: Settings | None = None) -> HostAgentClient:
    current_settings = settings or get_settings()
    return HostAgentClient(
        base_url=current_settings.app_maintenance_agent_base_url,
        token=current_settings.app_maintenance_agent_token,
        timeout_seconds=current_settings.maintenance_timeout_seconds,
        label="App maintenance agent",
    )


def get_maintenance_host_agent_client(settings: Settings | None = None) -> HostAgentClient:
    current_settings = settings or get_settings()
    return HostAgentClient(
        base_url=current_settings.host_agent_base_url,
        token=current_settings.host_agent_token,
        timeout_seconds=current_settings.maintenance_timeout_seconds,
        label="Host agent maintenance",
    )


def get_maintenance_pbs_agent_client(settings: Settings | None = None) -> HostAgentClient:
    current_settings = settings or get_settings()
    return HostAgentClient(
        base_url=current_settings.pbs_agent_base_url,
        token=current_settings.pbs_agent_token,
        timeout_seconds=current_settings.maintenance_timeout_seconds,
        label="PBS agent maintenance",
    )


def _status_from_payload(component: str, payload: dict) -> MaintenanceComponentStatus:
    status_payload = payload.get("status", payload)
    logs = [
        _command_result_from_payload(item)
        for item in status_payload.get("logs", [])
        if isinstance(item, dict)
    ]
    return MaintenanceComponentStatus(
        component=component,
        branch=status_payload.get("branch"),
        local_commit=status_payload.get("local_commit"),
        remote_commit=status_payload.get("remote_commit"),
        status=status_payload.get("status") or "error",
        error=status_payload.get("error"),
        logs=logs,
    )


def _command_result_from_payload(payload: dict) -> MaintenanceCommandResult:
    return MaintenanceCommandResult(
        command=str(payload.get("command") or ""),
        stdout=_mask(payload.get("stdout")) if isinstance(payload.get("stdout"), str) else None,
        stderr=_mask(payload.get("stderr")) if isinstance(payload.get("stderr"), str) else None,
        return_code=int(payload.get("return_code") or 0),
    )


def _mask(value: str | None) -> str | None:
    if value is None:
        return None
    masked = value
    for pattern in SECRET_PATTERNS:
        masked = pattern.sub(lambda match: f"{match.group(1)}=***" if match.lastindex == 2 else "***", masked)
    return masked
