from dataclasses import dataclass
from typing import Iterable

from app.core.config import get_settings
from app.models import DiskPreparationMode, ExternalBackupMode, ExternalDisk
from app.services.disk_identity import canonical_serial_number, serial_aliases
from app.services.host_agent import HostAgentError, get_host_agent_client, get_pbs_agent_client


@dataclass(frozen=True)
class AgentCommandResult:
    ok: bool
    message: str
    stdout_log: str | None
    stderr_log: str | None
    command_summary: str
    execution_cwd: str
    return_code: int | None
    payload: dict[str, object] | None = None


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


class AgentCompatibilityError(RuntimeError):
    pass


REQUIRED_PBS_CAPABILITIES = {
    "version-endpoint",
    "inspect-disk-alias-resolution",
    "external-export-objects-status",
    "external-export-objects-cleanup",
    "dedicated-pbs-eject",
}
REQUIRED_HOST_CAPABILITIES = {
    "version-endpoint",
    "qemu-usb-attach",
    "qemu-usb-detach",
}


class ExternalBackupAgentBridge:
    def __init__(self) -> None:
        self.host_client = get_host_agent_client()
        self.pbs_client = get_pbs_agent_client()
        self.settings = get_settings()

    def prepare_external_datastore(
        self,
        mount_path: str,
        target_path: str,
        mode: ExternalBackupMode,
        run_id: int | None = None,
    ) -> AgentCommandResult:
        payload: dict[str, object] = {"mount_path": mount_path, "target_path": target_path, "mode": mode.value}
        if run_id is not None:
            payload.update(self._callback_payload(run_id))
        return self._run_command(
            self.pbs_client,
            "/prepare-external-datastore",
            payload,
        )

    def prepare_disk_on_pbs(
        self,
        disk: ExternalDisk,
        mode: DiskPreparationMode,
    ) -> AgentCommandResult:
        return self._run_command(
            self.pbs_client,
            "/prepare-disk",
            {
                "disk": disk.serial_number,
                "mode": mode.value,
                "confirm_destructive": mode == DiskPreparationMode.DEDICATED_BACKUP,
            },
        )

    def prepare_dedicated_pbs_datastore(
        self,
        disk: ExternalDisk,
        datastore_name: str,
        run_id: int | None = None,
    ) -> AgentCommandResult:
        payload: dict[str, object] = {
            "disk": disk.serial_number,
            "datastore_name": datastore_name,
            "confirmation": True,
        }
        pbs_mount_path = getattr(disk, "pbs_mount_path", None)
        if pbs_mount_path:
            payload["mount_path"] = pbs_mount_path
        if run_id is not None:
            payload.update(self._callback_payload(run_id))
        return self._run_command(self.pbs_client, "/prepare-dedicated-pbs-datastore", payload)

    def run_external_export(
        self,
        target_path: str,
        datastore_name: str,
        mode: ExternalBackupMode,
        run_id: int | None = None,
        target_datastore_name: str | None = None,
        persist_target_datastore: bool = False,
    ) -> AgentCommandResult:
        payload: dict[str, object] = {
            "target_path": target_path,
            "datastore_name": datastore_name,
            "mode": mode.value,
        }
        if run_id is not None:
            payload.update(self._callback_payload(run_id))
        if target_datastore_name:
            payload["target_datastore_name"] = target_datastore_name
        payload["persist_target_datastore"] = persist_target_datastore
        return self._run_command(self.pbs_client, "/run-external-export", payload)

    def inspect_disk_on_pbs(self, disk: ExternalDisk) -> AgentCommandResult:
        errors: list[str] = []
        for identifier in _disk_identifiers(disk):
            try:
                result = self._run_command(self.pbs_client, "/inspect-disk", {"disk": identifier})
            except AgentCommandError as exc:
                errors.append(str(exc))
                continue
            if result.ok:
                return result
            errors.append(result.message)
        message = errors[-1] if errors else f"Unable to inspect disk `{disk.serial_number}` on PBS."
        return AgentCommandResult(
            ok=False,
            message=message,
            stdout_log=None,
            stderr_log="\n".join(errors) or None,
            command_summary="POST /inspect-disk",
            execution_cwd=self.pbs_client.base_url,
            return_code=1,
            payload=None,
        )

    def eject_dedicated_pbs_datastore(
        self,
        *,
        serial: str,
        datastore_name: str,
        mount_path: str,
    ) -> AgentCommandResult:
        return self._run_command(
            self.pbs_client,
            "/eject-dedicated-pbs-datastore",
            {
                "serial": serial,
                "datastore_name": datastore_name,
                "mount_path": mount_path,
            },
        )

    def cleanup_legacy_external_export_objects(self) -> AgentCommandResult:
        return self._run_command(self.pbs_client, "/cleanup-legacy-external-export-objects", {})

    def inspect_external_export_objects(self) -> AgentCommandResult:
        return self._run_command(self.pbs_client, "/external-export-objects/status", {})

    def cleanup_external_export_objects(self) -> AgentCommandResult:
        return self._run_command(self.pbs_client, "/external-export-objects/cleanup", {})

    def assert_external_backup_capabilities(self) -> None:
        _assert_capabilities(self.pbs_client, REQUIRED_PBS_CAPABILITIES, "Agent PBS incompatible ou non mis a jour. Mettre a jour l'agent PBS.")
        _assert_capabilities(self.host_client, REQUIRED_HOST_CAPABILITIES, "Agent Proxmox incompatible ou non mis a jour. Mettre a jour l'agent Proxmox.")

    def _run_command(self, client, path: str, payload: dict[str, object]) -> AgentCommandResult:
        try:
            result = client.post(path, payload)
        except HostAgentError as exc:
            raise AgentCommandError(
                str(exc),
                stdout_log=exc.stdout_log,
                stderr_log=exc.stderr_log,
                command_summary=exc.command_summary or f"POST {path}",
                execution_cwd=exc.execution_cwd or client.base_url,
                return_code=exc.return_code,
            ) from exc

        return AgentCommandResult(
            ok=result.ok,
            message=result.message,
            stdout_log=result.stdout_log,
            stderr_log=result.stderr_log,
            command_summary=result.command_summary or f"POST {path}",
            execution_cwd=result.execution_cwd or client.base_url,
            return_code=result.return_code,
            payload=result.payload,
        )

    def _callback_payload(self, run_id: int) -> dict[str, object]:
        base_url = self.settings.external_backup_callback_base_url.rstrip("/")
        return {
            "callback_run_id": run_id,
            "callback_url": f"{base_url}/external-backups/runs/{run_id}/log",
            "callback_token": self.settings.pbs_agent_token,
        }


def get_external_backup_agent_bridge() -> ExternalBackupAgentBridge:
    return ExternalBackupAgentBridge()


def _assert_capabilities(client, required: Iterable[str], message: str) -> None:
    try:
        payload = client.get_version()
    except HostAgentError as exc:
        raise AgentCompatibilityError(message) from exc
    capabilities = payload.get("capabilities")
    if not isinstance(capabilities, list):
        raise AgentCompatibilityError(message)
    missing = set(required) - {str(item) for item in capabilities}
    if missing:
        raise AgentCompatibilityError(f"{message} Capacites manquantes: {', '.join(sorted(missing))}.")


def _disk_identifiers(disk: ExternalDisk) -> list[str]:
    identifiers: list[str] = []
    raw_values = [
        disk.serial_number,
        getattr(disk, "canonical_serial_number", None),
        getattr(disk, "reported_serial_number", None),
        getattr(disk, "pbs_device_path", None),
        *(getattr(disk, "serial_aliases", None) or []),
    ]
    for value in raw_values:
        if isinstance(value, str) and value.strip() and value.strip() not in identifiers:
            identifiers.append(value.strip())
    for value in list(identifiers):
        for alias in serial_aliases(value):
            if alias and alias not in identifiers:
                identifiers.append(alias)
        canonical = canonical_serial_number(value)
        if canonical and canonical not in identifiers:
            identifiers.append(canonical)
    return identifiers
