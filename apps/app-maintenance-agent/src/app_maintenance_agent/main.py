import os
import json
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
    service_name: str = os.getenv(
        "APP_MAINTENANCE_AGENT_SERVICE",
        "proxmox-backup-orchestrator-app-maintenance-agent.service",
    )


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
        "compose": _compose_commands_payload(settings),
        "status": status_payload,
    }


@app.get("/maintenance/compose-command")
def maintenance_compose_command(
    _: None = Depends(require_token),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return _compose_commands_payload(settings)


@app.post("/maintenance/update")
def maintenance_update(
    _: None = Depends(require_token),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    current_status = _git_status(settings)
    if current_status["status"] == "error":
        return {
            "ok": False,
            "message": current_status["error"] or "Maintenance check failed.",
            "action_status": "error",
            "status": current_status,
            "logs": current_status["logs"],
            "return_code": 1,
        }
    if current_status["local_commit"] == current_status["remote_commit"]:
        return {
            "ok": True,
            "message": "Already up to date.",
            "action_status": "up_to_date",
            "status": current_status,
            "logs": current_status["logs"],
            "return_code": 0,
        }

    repo = Path(settings.repo_path)
    logs = _run_sequence(
        repo,
        [
            _env_file_check_command(),
            ["git", "status", "--short"],
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            ["git", "rev-parse", "HEAD"],
            ["git", "rev-parse", "@{u}"],
            ["git", "pull", "--ff-only"],
            _compose_command(settings),
        ],
        settings.timeout_seconds,
    )
    if all(item["return_code"] == 0 for item in logs):
        logs.append(_verify_api_notification_env(repo, settings))
    status_payload = _git_status(settings)
    if all(item["return_code"] == 0 for item in logs) and status_payload["status"] != "error":
        logs.append(_restart_agent_service(repo, settings))
    ok = all(item["return_code"] == 0 for item in logs) and status_payload["status"] != "error"
    return {
        "ok": ok,
        "message": "App VM update completed." if ok else "App VM update failed.",
        "action_status": "success" if ok else "error",
        "status": status_payload,
        "logs": logs,
        "return_code": 0 if ok else 1,
    }


def _git_status(settings: Settings) -> dict[str, Any]:
    repo = Path(settings.repo_path)
    logs = _run_sequence(
        repo,
        [_env_file_check_command(), _compose_config_command(settings), ["git", "fetch"], ["git", "status", "--short"]],
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
    if command == _env_file_check_command():
        env_file = repo / ".env"
        if not env_file.exists():
            return {
                "command": _command_text(command),
                "stdout": None,
                "stderr": ".env not found at APP_REPO_PATH",
                "return_code": 1,
            }
        return {
            "command": _command_text(command),
            "stdout": ".env found at APP_REPO_PATH",
            "stderr": None,
            "return_code": 0,
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
        return ["docker-compose", "--env-file", ".env", "-f", settings.compose_file, "up", "--build", "-d"]
    return ["docker", "compose", "--env-file", ".env", "-f", settings.compose_file, "up", "--build", "-d"]


def _compose_config_command(settings: Settings) -> list[str]:
    if shutil.which("docker-compose"):
        return ["docker-compose", "--env-file", ".env", "-f", settings.compose_file, "config", "--quiet"]
    return ["docker", "compose", "--env-file", ".env", "-f", settings.compose_file, "config", "--quiet"]


def _compose_verify_notifications_command(settings: Settings) -> list[str]:
    verify_script = (
        "import json, os; "
        "print(json.dumps({"
        "'NOTIFICATIONS_ENABLED': os.getenv('NOTIFICATIONS_ENABLED'), "
        "'NTFY_BASE_URL': os.getenv('NTFY_BASE_URL'), "
        "'NTFY_USERNAME': os.getenv('NTFY_USERNAME'), "
        "'NTFY_TOPIC_SET': bool(os.getenv('NTFY_TOPIC')), "
        "'NTFY_TOPIC_IS_DEFAULT': os.getenv('NTFY_TOPIC') == 'proxmox-backup-orchestrator'"
        "}))"
    )
    if shutil.which("docker-compose"):
        return [
            "docker-compose",
            "--env-file",
            ".env",
            "-f",
            settings.compose_file,
            "exec",
            "-T",
            "api",
            "python",
            "-c",
            verify_script,
        ]
    return [
        "docker",
        "compose",
        "--env-file",
        ".env",
        "-f",
        settings.compose_file,
        "exec",
        "-T",
        "api",
        "python",
        "-c",
        verify_script,
    ]


def _env_file_check_command() -> list[str]:
    return ["check-env-file", ".env"]


def _restart_agent_service_command(settings: Settings) -> list[str]:
    if shutil.which("systemd-run"):
        return [
            "systemd-run",
            "--on-active=10",
            "--unit",
            "pbo-app-maintenance-agent-restart",
            "systemctl",
            "restart",
            settings.service_name,
        ]
    return ["systemctl", "try-restart", settings.service_name, "--no-block"]


def _verify_api_notification_env(repo: Path, settings: Settings) -> dict[str, Any]:
    expected = _read_env_file(repo / ".env")
    command = _compose_verify_notifications_command(settings)
    result = _run(repo, command, settings.timeout_seconds)
    if result["return_code"] != 0:
        return result

    try:
        actual = json.loads(result["stdout"] or "{}")
    except json.JSONDecodeError as exc:
        result["stderr"] = f"Unable to parse API notification env verification output: {exc}"
        result["return_code"] = 1
        return result

    errors: list[str] = []
    expected_enabled = expected.get("NOTIFICATIONS_ENABLED")
    expected_base_url = expected.get("NTFY_BASE_URL")
    expected_username = expected.get("NTFY_USERNAME")
    expected_topic = expected.get("NTFY_TOPIC")

    if expected_enabled and actual.get("NOTIFICATIONS_ENABLED") != expected_enabled:
        errors.append(
            f"NOTIFICATIONS_ENABLED expected {expected_enabled!r} but API has {actual.get('NOTIFICATIONS_ENABLED')!r}"
        )
    if expected_base_url and actual.get("NTFY_BASE_URL") != expected_base_url:
        errors.append(f"NTFY_BASE_URL expected {expected_base_url!r} but API has {actual.get('NTFY_BASE_URL')!r}")
    if expected_username and actual.get("NTFY_USERNAME") != expected_username:
        errors.append(f"NTFY_USERNAME expected {expected_username!r} but API has {actual.get('NTFY_USERNAME')!r}")
    if expected_topic and (not actual.get("NTFY_TOPIC_SET") or actual.get("NTFY_TOPIC_IS_DEFAULT")):
        errors.append("NTFY_TOPIC from .env is not visible in API container.")

    result["stdout"] = (
        "API notification env verified: "
        f"NOTIFICATIONS_ENABLED={actual.get('NOTIFICATIONS_ENABLED')!r}, "
        f"NTFY_BASE_URL={actual.get('NTFY_BASE_URL')!r}, "
        f"NTFY_USERNAME={actual.get('NTFY_USERNAME')!r}, "
        f"NTFY_TOPIC_SET={actual.get('NTFY_TOPIC_SET')!r}, "
        f"NTFY_TOPIC_IS_DEFAULT={actual.get('NTFY_TOPIC_IS_DEFAULT')!r}"
    )
    if errors:
        result["stderr"] = "Production .env values are not visible inside API container: " + "; ".join(errors)
        result["return_code"] = 1
    return result


def _restart_agent_service(repo: Path, settings: Settings) -> dict[str, Any]:
    command = _restart_agent_service_command(settings)
    if not shutil.which("systemctl"):
        return {
            "command": _command_text(command),
            "stdout": None,
            "stderr": "systemctl is not available; restart app maintenance agent manually.",
            "return_code": 1,
        }
    return _run(repo, command, settings.timeout_seconds)


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        values[key] = value
    return values


def _compose_commands_payload(settings: Settings) -> dict[str, str]:
    return {
        "config": _command_text(_compose_config_command(settings)),
        "update": _command_text(_compose_command(settings)),
        "verify_notifications": _command_text(_compose_verify_notifications_command(settings)),
    }


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
