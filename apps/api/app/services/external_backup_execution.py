from dataclasses import dataclass

from app.models import ExternalBackupMode, ExternalDisk
from app.services.external_backup_agent import AgentCommandError
from app.services.external_backup_agent import get_external_backup_agent_bridge


@dataclass(frozen=True)
class ExternalBackupExecutionStep:
    message: str
    stdout_log: str | None
    stderr_log: str | None
    command_summary: str
    execution_cwd: str
    return_code: int | None


@dataclass(frozen=True)
class ExternalBackupExecutionResult:
    prepare: ExternalBackupExecutionStep
    export: ExternalBackupExecutionStep


class ExternalBackupExecutionService:
    def __init__(self) -> None:
        self._bridge = get_external_backup_agent_bridge()

    def execute(
        self,
        *,
        disk: ExternalDisk,
        target_path: str,
        datastore_name: str,
        mode: ExternalBackupMode,
    ) -> ExternalBackupExecutionResult:
        prepare = self._bridge.prepare_external_datastore(disk, target_path, mode)
        if not prepare.ok:
            raise RuntimeError(prepare.message)

        export = self._bridge.run_external_export(target_path, datastore_name, mode)
        if not export.ok:
            raise AgentCommandError(
                export.message,
                stdout_log=export.stdout_log,
                stderr_log=export.stderr_log,
                command_summary=export.command_summary,
                return_code=export.return_code,
            )
        return ExternalBackupExecutionResult(
            prepare=ExternalBackupExecutionStep(
                message=prepare.message,
                stdout_log=prepare.stdout_log,
                stderr_log=prepare.stderr_log,
                command_summary=prepare.command_summary,
                execution_cwd=prepare.execution_cwd,
                return_code=prepare.return_code,
            ),
            export=ExternalBackupExecutionStep(
                message=export.message,
                stdout_log=export.stdout_log,
                stderr_log=export.stderr_log,
                command_summary=export.command_summary,
                execution_cwd=export.execution_cwd,
                return_code=export.return_code,
            ),
        )


def get_external_backup_execution_service() -> ExternalBackupExecutionService:
    return ExternalBackupExecutionService()
