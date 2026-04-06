from dataclasses import dataclass

from app.models import DiskPreparationMode, ExternalDisk
from app.services.host_agent import HostAgentError, get_host_agent_client


@dataclass(frozen=True)
class DiskInspectionResult:
    ok: bool
    filesystem_type: str | None
    mount_path_suggestion: str
    message: str


@dataclass(frozen=True)
class DiskPreparationAgentResult:
    ok: bool
    mount_path: str | None
    filesystem_type: str | None
    message: str


class DiskPreparationAgentBridge:
    def __init__(self) -> None:
        self.client = get_host_agent_client()

    def inspect_disk(self, disk: ExternalDisk, mount_base_path: str | None = None) -> DiskInspectionResult:
        suggestion = f"{mount_base_path or '/mnt/pbo'}/{disk.serial_number}"
        return DiskInspectionResult(
            ok=True,
            filesystem_type=disk.filesystem_type,
            mount_path_suggestion=suggestion,
            message="Disk preparation will be executed by the host agent HTTP API.",
        )

    def prepare_disk(
        self,
        disk: ExternalDisk,
        mode: DiskPreparationMode,
        mount_base_path: str | None = None,
    ) -> DiskPreparationAgentResult:
        payload = {
            "disk": disk.serial_number,
            "mode": mode.value,
            "mount_base_path": mount_base_path,
            "confirm_destructive": mode == DiskPreparationMode.DEDICATED_BACKUP,
        }
        try:
            result = self.client.post("/prepare-disk", payload)
        except HostAgentError as exc:
            return DiskPreparationAgentResult(
                ok=False,
                mount_path=None,
                filesystem_type=None,
                message=str(exc),
            )

        return DiskPreparationAgentResult(
            ok=result.ok,
            mount_path=_optional_string(result.payload.get("mount_path")),
            filesystem_type=_optional_string(result.payload.get("filesystem_type")),
            message=result.message,
        )


def _optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def get_disk_preparation_agent_bridge() -> DiskPreparationAgentBridge:
    return DiskPreparationAgentBridge()
