from dataclasses import dataclass
from typing import Any

from app.models import DiskPreparationMode, ExternalBackupMode, ExternalDisk
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
    target_path: str


class ExternalBackupExecutionService:
    def __init__(self) -> None:
        self._bridge = get_external_backup_agent_bridge()

    def execute(
        self,
        *,
        disk: ExternalDisk,
        datastore_name: str,
        mode: ExternalBackupMode,
    ) -> ExternalBackupExecutionResult:
        disk_prepare_mode = (
            DiskPreparationMode.DEDICATED_BACKUP
            if mode == ExternalBackupMode.DEDICATED
            else DiskPreparationMode.PRESERVE_EXISTING_DATA
        )
        disk_prepare = self._bridge.prepare_disk_on_pbs(disk, disk_prepare_mode)
        if not disk_prepare.ok:
            raise RuntimeError(disk_prepare.message)

        mount_path = _extract_mount_path(disk_prepare.payload)
        if not mount_path:
            raise RuntimeError("PBS agent did not return a mount path after disk preparation.")

        target_path = build_export_target_path(mount_path, disk.serial_number, mode)
        prepare = self._bridge.prepare_external_datastore(mount_path, target_path, mode)
        if not prepare.ok:
            raise RuntimeError(prepare.message)

        actual_target_path = _extract_actual_target_path(prepare.payload) or target_path
        export = self._bridge.run_external_export(actual_target_path, datastore_name, mode)
        if not export.ok:
            raise AgentCommandError(
                export.message,
                stdout_log=export.stdout_log,
                stderr_log=export.stderr_log,
                command_summary=export.command_summary,
                execution_cwd=export.execution_cwd,
                return_code=export.return_code,
            )
        return ExternalBackupExecutionResult(
            prepare=ExternalBackupExecutionStep(
                message=f"{disk_prepare.message} {prepare.message}".strip(),
                stdout_log=_merge_logs(
                    disk_prepare.stdout_log,
                    _format_prepare_target_details(prepare.payload, target_path, actual_target_path),
                    prepare.stdout_log,
                ),
                stderr_log=_merge_logs(disk_prepare.stderr_log, prepare.stderr_log),
                command_summary=_merge_logs(disk_prepare.command_summary, prepare.command_summary) or "",
                execution_cwd=_merge_logs(disk_prepare.execution_cwd, prepare.execution_cwd) or "",
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
            target_path=actual_target_path,
        )


def build_export_target_path(mount_path: str, serial_number: str, mode: ExternalBackupMode) -> str:
    base_path = mount_path.rstrip("/")
    if mode == ExternalBackupMode.DEDICATED:
        return f"{base_path}/pbs-datastore"
    return f"{base_path}/proxmox-backup-orchestrator/{serial_number}/pbs-datastore"


def _extract_mount_path(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    raw_value = payload.get("mount_path")
    if not isinstance(raw_value, str):
        return None
    stripped = raw_value.strip()
    return stripped or None


def _extract_actual_target_path(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("actual_target_path", "target_path"):
        raw_value = payload.get(key)
        if isinstance(raw_value, str) and raw_value.strip():
            return raw_value.strip()
    return None


def _format_prepare_target_details(
    payload: dict[str, Any] | None,
    requested_target_path: str,
    actual_target_path: str,
) -> str:
    details = [
        f"Requested target path: {requested_target_path}",
        f"Actual datastore path: {actual_target_path}",
    ]
    if isinstance(payload, dict):
        loop_image_path = payload.get("loop_image_path")
        if isinstance(loop_image_path, str) and loop_image_path.strip():
            details.append(f"Loop image path: {loop_image_path.strip()}")
    return "\n".join(details)


def _merge_logs(*values: str | None) -> str | None:
    merged = "\n\n".join(value for value in values if value)
    return merged or None


def get_external_backup_execution_service() -> ExternalBackupExecutionService:
    return ExternalBackupExecutionService()
