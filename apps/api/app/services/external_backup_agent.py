import json
import subprocess
from dataclasses import dataclass
from pathlib import PurePosixPath

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
    execution_cwd: str
    return_code: int | None


class AgentCommandError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        stdout_log: str | None,
        stderr_log: str | None,
        command_summary: str,
        execution_cwd: str,
        return_code: int | None,
    ) -> None:
        super().__init__(message)
        self.stdout_log = stdout_log
        self.stderr_log = stderr_log
        self.command_summary = command_summary
        self.execution_cwd = execution_cwd
        self.return_code = return_code


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
        command = [self.settings.agent_exec_python_path, "-m", "agent.main", *args]
        command_summary = " ".join(command)
        execution_cwd = str(PurePosixPath(self.settings.agent_exec_workdir))
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.settings.host_agent_timeout_seconds,
                cwd=execution_cwd,
                check=False,
            )
        except FileNotFoundError as exc:
            raise AgentCommandError(
                f"Host agent command could not be started: `{command_summary}` in `{execution_cwd}`.",
                stdout_log=None,
                stderr_log=str(exc),
                command_summary=command_summary,
                execution_cwd=execution_cwd,
                return_code=127,
            ) from exc
        except subprocess.TimeoutExpired as exc:
            stdout_log = _truncate_log(exc.stdout if isinstance(exc.stdout, str) else None)
            stderr_log = _truncate_log(exc.stderr if isinstance(exc.stderr, str) else None)
            raise AgentCommandError(
                f"Host agent command timed out after {self.settings.host_agent_timeout_seconds} seconds: `{command_summary}` in `{execution_cwd}`.",
                stdout_log=stdout_log,
                stderr_log=stderr_log,
                command_summary=command_summary,
                execution_cwd=execution_cwd,
                return_code=None,
            ) from exc
        except OSError as exc:
            raise AgentCommandError(
                f"Host agent command failed to start: `{command_summary}` in `{execution_cwd}`.",
                stdout_log=None,
                stderr_log=str(exc),
                command_summary=command_summary,
                execution_cwd=execution_cwd,
                return_code=None,
            ) from exc
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
                    execution_cwd=execution_cwd,
                    returncode=completed.returncode,
                ),
                stdout_log=_truncate_log(str(payload.get("stdout_log") or "")) or stdout_log,
                stderr_log=_truncate_log(str(payload.get("stderr_log") or "")) or stderr_log,
                command_summary=str(payload.get("command_summary") or command_summary),
                execution_cwd=str(payload.get("execution_cwd") or execution_cwd),
                return_code=_payload_return_code(payload, completed.returncode),
            )
            raise AgentCommandError(
                _format_failure(command_summary, execution_cwd, stdout_log, stderr_log, completed.returncode),
                stdout_log=stdout_log,
                stderr_log=stderr_log,
                command_summary=command_summary,
                execution_cwd=execution_cwd,
                return_code=completed.returncode,
            )

        if payload is None:
            raise AgentCommandError(
                f"Host agent returned invalid JSON for `{command_summary}` in `{execution_cwd}`.",
                stdout_log=stdout_log,
                stderr_log=stderr_log,
                command_summary=command_summary,
                execution_cwd=execution_cwd,
                return_code=completed.returncode,
            )

        return AgentCommandResult(
            ok=bool(payload.get("ok")),
            message=str(payload.get("message") or "Host agent command completed."),
            stdout_log=_truncate_log(payload.get("stdout_log")) or stdout_log,
            stderr_log=_truncate_log(payload.get("stderr_log")) or stderr_log,
            command_summary=str(payload.get("command_summary") or command_summary),
            execution_cwd=str(payload.get("execution_cwd") or execution_cwd),
            return_code=_payload_return_code(payload, completed.returncode),
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
    execution_cwd: str,
    stdout_log: str | None,
    stderr_log: str | None,
    returncode: int,
) -> str:
    details = [
        f"Host agent command failed with exit code {returncode}: `{command_summary}`.",
        f"cwd: `{execution_cwd}`",
    ]
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
    execution_cwd: str,
    returncode: int,
) -> str:
    message = str(payload.get("message") or "Host agent command failed.")
    payload_cwd = str(payload.get("execution_cwd") or execution_cwd)
    details = [f"{message} (exit code {returncode}, command `{command_summary}`, cwd `{payload_cwd}`)."]
    payload_stderr = _truncate_log(str(payload.get("stderr_log") or "")) if payload.get("stderr_log") else None
    if payload_stderr:
        details.append(f"stderr: {payload_stderr[:500]}")
    elif stderr_log:
        details.append(f"stderr: {stderr_log[:500]}")
    if stdout_log:
        details.append(f"stdout: {stdout_log[:500]}")
    return " ".join(details)


def _payload_return_code(payload: dict[str, object], fallback: int | None) -> int | None:
    raw_value = payload.get("return_code")
    if raw_value is None:
        return fallback
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return fallback


def get_external_backup_agent_bridge() -> ExternalBackupAgentBridge:
    return ExternalBackupAgentBridge()
