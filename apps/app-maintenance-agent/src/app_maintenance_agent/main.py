import os
import re
import secrets
import shutil
import socket
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, status


SECRET_PATTERNS = [
    re.compile(r"(?i)(token|secret|password|key)=([^\s]+)"),
    re.compile(r"(?i)(Authorization:\s*)([^\s]+)"),
]


@dataclass(frozen=True)
class Settings:
    host: str = os.getenv("APP_MAINTENANCE_AGENT_HOST", "127.0.0.1")
    port: int = int(os.getenv("APP_MAINTENANCE_AGENT_PORT", "8092"))
    token: str = os.getenv("APP_MAINTENANCE_AGENT_TOKEN", "")
    repo_path: str = os.getenv("APP_REPO_PATH", "/opt/proxmox_backup_orchestrator")
    compose_file: str = os.getenv("APP_COMPOSE_FILE", "infra/docker/docker-compose.yml")
    timeout_seconds: float = float(os.getenv("APP_MAINTENANCE_TIMEOUT_SECONDS", "300"))


app = FastAPI(title="Proxmox Backup Orchestrator App Maintenance Agent", version="0.1.0")
SERVER_STARTED_AT = datetime.now(timezone.utc).isoformat()


def get_settings() -> Settings:
    return Settings()


def require_token(
    x_agent_token: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    if not settings.token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="APP_MAINTENANCE_AGENT_TOKEN is not configured.",
        )
    if x_agent_token is None or not secrets.compare_digest(x_agent_token, settings.token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid agent token.")


@app.get("/health")
def health(_: None = Depends(require_token)) -> dict[str, Any]:
    return {
        "ok": True,
        "hostname": socket.gethostname(),
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "server_started_at": SERVER_STARTED_AT,
    }


@app.post("/maintenance/check")
def maintenance_check(
    _: None = Depends(require_token),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    status_payload = _git_status(settings)
    return {
        "ok": status_payload["status"] != "error",
        "message": "App VM maintenance status checked.",
        "status": status_payload,
    }


@app.post("/maintenance/update")
def maintenance_update(
    _: None = Depends(require_token),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    repo = Path(settings.repo_path)
    logs = _run_sequence(
        repo,
        [
            ["git", "fetch"],
            ["git", "status", "--short"],
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            ["git", "rev-parse", "HEAD"],
            ["git", "rev-parse", "@{u}"],
            ["git", "pull", "--ff-only"],
            _compose_command(settings),
        ],
        settings.timeout_seconds,
    )
    status_payload = _git_status(settings)
    ok = all(item["return_code"] == 0 for item in logs) and status_payload["status"] != "error"
    return {
        "ok": ok,
        "message": "App VM update completed." if ok else "App VM update failed.",
        "status": status_payload,
        "logs": logs,
        "return_code": 0 if ok else 1,
    }


def _git_status(settings: Settings) -> dict[str, Any]:
    repo = Path(settings.repo_path)
    logs = _run_sequence(
        repo,
        [["git", "fetch"], ["git", "status", "--short"]],
        settings.timeout_seconds,
    )
    branch = _run(repo, ["git", "rev-parse", "--abbrev-ref", "HEAD"], settings.timeout_seconds)
    local = _run(repo, ["git", "rev-parse", "HEAD"], settings.timeout_seconds)
    remote = _run(repo, ["git", "rev-parse", "@{u}"], settings.timeout_seconds)
    logs.extend([branch, local, remote])
    error = next((item["stderr"] or item["stdout"] for item in logs if item["return_code"] != 0), None)
    state = "error" if error else ("up_to_date" if local["stdout"] == remote["stdout"] else "update_available")
    return {
        "branch": branch["stdout"],
        "local_commit": local["stdout"],
        "remote_commit": remote["stdout"],
        "status": state,
        "error": error,
        "logs": logs,
    }


def _run_sequence(repo: Path, commands: list[list[str]], timeout_seconds: float) -> list[dict[str, Any]]:
    logs: list[dict[str, Any]] = []
    for command in commands:
        result = _run(repo, command, timeout_seconds)
        logs.append(result)
        if result["return_code"] != 0:
            break
    return logs


def _run(repo: Path, command: list[str], timeout_seconds: float) -> dict[str, Any]:
    if not repo.exists():
        return {
            "command": _command_text(command),
            "stdout": None,
            "stderr": f"Repository path does not exist: {repo}",
            "return_code": 1,
        }

    try:
        completed = subprocess.run(
            command,
            cwd=repo,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        return {"command": _command_text(command), "stdout": None, "stderr": _mask(str(exc)), "return_code": 127}
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else None
        stderr = exc.stderr if isinstance(exc.stderr, str) else None
        return {
            "command": _command_text(command),
            "stdout": _mask(stdout),
            "stderr": _mask((stderr or "") + f"\nTimed out after {timeout_seconds} seconds."),
            "return_code": 124,
        }

    return {
        "command": _command_text(command),
        "stdout": _mask(completed.stdout.strip()) or None,
        "stderr": _mask(completed.stderr.strip()) or None,
        "return_code": completed.returncode,
    }


def _compose_command(settings: Settings) -> list[str]:
    if shutil.which("docker-compose"):
        return ["docker-compose", "-f", settings.compose_file, "up", "--build", "-d"]
    return ["docker", "compose", "-f", settings.compose_file, "up", "--build", "-d"]


def _command_text(command: list[str]) -> str:
    return " ".join(command)


def _mask(value: str | None) -> str | None:
    if value is None:
        return None
    masked = value
    for pattern in SECRET_PATTERNS:
        masked = pattern.sub(lambda match: f"{match.group(1)}=***", masked)
    return masked


def serve() -> None:
    settings = Settings()
    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    serve()
