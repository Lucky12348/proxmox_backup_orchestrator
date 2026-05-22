from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

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
    current_settings = settings or get_settings()
    return _check_git_status("app-vm", Path(current_settings.app_repo_path), current_settings.maintenance_timeout_seconds)


def update_app(settings: Settings | None = None) -> MaintenanceActionResult:
    current_settings = settings or get_settings()
    repo = Path(current_settings.app_repo_path)
    timeout = current_settings.maintenance_timeout_seconds
    logs = _run_sequence(
        repo,
        [
            ["git", "fetch"],
            ["git", "status", "--short"],
            ["git", "rev-parse", "HEAD"],
            ["git", "rev-parse", "@{u}"],
            ["git", "pull", "--ff-only"],
            _compose_command(current_settings),
        ],
        timeout,
    )
    return MaintenanceActionResult("app-vm", check_app_status(current_settings), logs)


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


def _check_git_status(component: str, repo: Path, timeout: float) -> MaintenanceComponentStatus:
    logs: list[MaintenanceCommandResult] = []
    try:
        logs.extend(_run_sequence(repo, [["git", "fetch"], ["git", "status", "--short"]], timeout))
        branch = _run(repo, ["git", "rev-parse", "--abbrev-ref", "HEAD"], timeout)
        local = _run(repo, ["git", "rev-parse", "HEAD"], timeout)
        remote = _run(repo, ["git", "rev-parse", "@{u}"], timeout)
        logs.extend([branch, local, remote])
        status = "up_to_date" if local.stdout == remote.stdout else "update_available"
        if any(log.return_code != 0 for log in logs):
            status = "error"
        return MaintenanceComponentStatus(
            component=component,
            branch=branch.stdout,
            local_commit=local.stdout,
            remote_commit=remote.stdout,
            status=status,
            error=_first_error(logs),
            logs=logs,
        )
    except Exception as exc:
        return MaintenanceComponentStatus(
            component=component,
            branch=None,
            local_commit=None,
            remote_commit=None,
            status="error",
            error=_mask(str(exc)),
            logs=logs,
        )


def _run_sequence(repo: Path, commands: Iterable[list[str]], timeout: float) -> list[MaintenanceCommandResult]:
    logs: list[MaintenanceCommandResult] = []
    for command in commands:
        result = _run(repo, command, timeout)
        logs.append(result)
        if result.return_code != 0:
            break
    return logs


def _run(repo: Path, command: list[str], timeout: float) -> MaintenanceCommandResult:
    if not repo.exists():
        return MaintenanceCommandResult(_command_text(command), None, f"Repository path does not exist: {repo}", 1)

    try:
        completed = subprocess.run(
            command,
            cwd=repo,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        return MaintenanceCommandResult(_command_text(command), None, str(exc), 127)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else None
        stderr = exc.stderr if isinstance(exc.stderr, str) else None
        return MaintenanceCommandResult(
            _command_text(command),
            _mask(stdout),
            _mask((stderr or "") + f"\nTimed out after {timeout} seconds."),
            124,
        )

    return MaintenanceCommandResult(
        _command_text(command),
        _mask(completed.stdout.strip()) or None,
        _mask(completed.stderr.strip()) or None,
        completed.returncode,
    )


def _compose_command(settings: Settings) -> list[str]:
    compose_file = settings.app_compose_file
    if shutil.which("docker-compose"):
        return ["docker-compose", "-f", compose_file, "up", "--build", "-d"]
    return ["docker", "compose", "-f", compose_file, "up", "--build", "-d"]


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


def _command_text(command: list[str]) -> str:
    return " ".join(command)


def _first_error(logs: list[MaintenanceCommandResult]) -> str | None:
    for log in logs:
        if log.return_code != 0:
            return log.stderr or log.stdout or f"{log.command} failed with exit {log.return_code}"
    return None


def _mask(value: str | None) -> str | None:
    if value is None:
        return None
    masked = value
    for pattern in SECRET_PATTERNS:
        masked = pattern.sub(lambda match: f"{match.group(1)}=***" if match.lastindex == 2 else "***", masked)
    return masked
