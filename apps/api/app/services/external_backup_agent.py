import json
import subprocess
from dataclasses import dataclass

from app.core.config import get_settings
from app.models import ExternalBackupMode, ExternalDisk


MAX_LOG_LENGTH = 32000


@dataclass(frozen=True)
class AgentCommandResult:
    ok: bool
    message: str
    stdout_log: str | None
    stderr_log: str | None
    command_summary: str


class AgentCommandError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        stdout_log: str | None,
        stderr_log: str | None,
        command_summary: str,
    ) -> None:
        super().__init__(message)
        self.stdout_log = stdout_log
        self.stderr_log = stderr_log
        self.command_summary = command_summary


class ExternalBackupAgentBridge:
    def __init__(self) -> None:
        self.settings = get_settings()

    def prepare_external_datastore(
        self,
        disk: ExternalDisk,
        target_path: str,
        mode: ExternalBackupMode,
    ) -> AgentCommandResult:
        mount_path = disk.mount_path
        if not mount_path:
            raise RuntimeError("Disk has no mount path, so the host agent cannot prepare the export target.")

        return self._run_command(
            [
                "prepare-external-datastore",
                "--mount-path",
                mount_path,
                "--target-path",
                target_path,
                "--mode",
                mode.value,
            ]
        )

    def run_external_export(
        self,
        target_path: str,
        datastore_name: str,
        mode: ExternalBackupMode,
    ) -> AgentCommandResult:
        return self._run_command(
            [
                "run-external-export",
                "--target-path",
                target_path,
                "--datastore-name",
                datastore_name,
                "--mode",
                mode.value,
            ]
        )

    def _run_command(self, args: list[str]) -> AgentCommandResult:
        command = [*self.settings.host_agent_command_parts, *args]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=self.settings.host_agent_timeout_seconds,
            cwd=self.settings.host_agent_workdir,
            check=False,
        )
        command_summary = " ".join(command)
        stdout_log = _truncate_log(completed.stdout)
        stderr_log = _truncate_log(completed.stderr)
        payload = _parse_payload(completed.stdout)

        if completed.returncode != 0:
            if payload is not None:
                raise AgentCommandError(
                    _format_payload_failure(
                        command_summary=command_summary,
                        payload=payload,
                        stdout_log=stdout_log,
                        stderr_log=stderr_log,
                        returncode=completed.returncode,
                    ),
                    stdout_log=_truncate_log(str(payload.get("stdout_log") or "")) or stdout_log,
                    stderr_log=_truncate_log(str(payload.get("stderr_log") or "")) or stderr_log,
                    command_summary=str(payload.get("command_summary") or command_summary),
                )
            raise AgentCommandError(
                _format_failure(command_summary, stdout_log, stderr_log, completed.returncode),
                stdout_log=stdout_log,
                stderr_log=stderr_log,
                command_summary=command_summary,
            )

        if payload is None:
            raise AgentCommandError(
                f"Host agent returned invalid JSON for `{command_summary}`.",
                stdout_log=stdout_log,
                stderr_log=stderr_log,
                command_summary=command_summary,
            )

        return AgentCommandResult(
            ok=bool(payload.get("ok")),
            message=str(payload.get("message") or "Host agent command completed."),
            stdout_log=_truncate_log(payload.get("stdout_log")) or stdout_log,
            stderr_log=_truncate_log(payload.get("stderr_log")) or stderr_log,
            command_summary=str(payload.get("command_summary") or command_summary),
        )


def _truncate_log(value: str | None) -> str | None:
    if value is None:
        return None

    stripped = value.strip()
    if not stripped:
        return None

    if len(stripped) <= MAX_LOG_LENGTH:
        return stripped

    return f"{stripped[:MAX_LOG_LENGTH]}\n...[truncated]"


def _format_failure(
    command_summary: str,
    stdout_log: str | None,
    stderr_log: str | None,
    returncode: int,
) -> str:
    details = [f"Host agent command failed with exit code {returncode}: `{command_summary}`."]
    if stderr_log:
        details.append(f"stderr: {stderr_log[:500]}")
    if stdout_log:
        details.append(f"stdout: {stdout_log[:500]}")
    return " ".join(details)


def _parse_payload(raw_stdout: str) -> dict[str, object] | None:
    try:
        payload = json.loads(raw_stdout)
    except json.JSONDecodeError:
        return None

    return payload if isinstance(payload, dict) else None


def _format_payload_failure(
    command_summary: str,
    payload: dict[str, object],
    stdout_log: str | None,
    stderr_log: str | None,
    returncode: int,
) -> str:
    message = str(payload.get("message") or "Host agent command failed.")
    details = [f"{message} (exit code {returncode}, command `{command_summary}`)."]
    payload_stderr = _truncate_log(str(payload.get("stderr_log") or "")) if payload.get("stderr_log") else None
    if payload_stderr:
        details.append(f"stderr: {payload_stderr[:500]}")
    elif stderr_log:
        details.append(f"stderr: {stderr_log[:500]}")
    if stdout_log:
        details.append(f"stdout: {stdout_log[:500]}")
    return " ".join(details)


def get_external_backup_agent_bridge() -> ExternalBackupAgentBridge:
    return ExternalBackupAgentBridge()
