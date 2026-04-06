from dataclasses import dataclass

from app.models import ExternalBackupMode, ExternalDisk
from app.services.host_agent import HostAgentError, get_host_agent_client


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
        self.client = get_host_agent_client()

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
            "/prepare-external-datastore",
            {"mount_path": mount_path, "target_path": target_path, "mode": mode.value},
        )

    def run_external_export(
        self,
        target_path: str,
        datastore_name: str,
        mode: ExternalBackupMode,
    ) -> AgentCommandResult:
        return self._run_command(
            "/run-external-export",
            {"target_path": target_path, "datastore_name": datastore_name, "mode": mode.value},
        )

    def _run_command(self, path: str, payload: dict[str, str]) -> AgentCommandResult:
        try:
            result = self.client.post(path, payload)
        except HostAgentError as exc:
            raise AgentCommandError(
                str(exc),
                stdout_log=exc.stdout_log,
                stderr_log=exc.stderr_log,
                command_summary=exc.command_summary or f"POST {path}",
                execution_cwd=exc.execution_cwd or self.client.settings.host_agent_base_url,
                return_code=exc.return_code,
            ) from exc

        return AgentCommandResult(
            ok=result.ok,
            message=result.message,
            stdout_log=result.stdout_log,
            stderr_log=result.stderr_log,
            command_summary=result.command_summary or f"POST {path}",
            execution_cwd=result.execution_cwd or self.client.settings.host_agent_base_url,
            return_code=result.return_code,
        )


def get_external_backup_agent_bridge() -> ExternalBackupAgentBridge:
    return ExternalBackupAgentBridge()
