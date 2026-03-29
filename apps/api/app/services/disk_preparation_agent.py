from dataclasses import dataclass
from pathlib import PurePosixPath

from app.models import DiskPreparationMode, ExternalDisk


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
    def inspect_disk(self, disk: ExternalDisk, mount_base_path: str | None = None) -> DiskInspectionResult:
        base_path = PurePosixPath(mount_base_path or "/mnt/pbo")
        suggestion = str(base_path / disk.serial_number)
        return DiskInspectionResult(
            ok=True,
            filesystem_type=disk.filesystem_type,
            mount_path_suggestion=suggestion,
            message="Stub agent boundary: would inspect partitions and suggest a mount path.",
        )

    def prepare_disk(
        self,
        disk: ExternalDisk,
        mode: DiskPreparationMode,
        mount_base_path: str | None = None,
    ) -> DiskPreparationAgentResult:
        base_path = PurePosixPath(mount_base_path or "/mnt/pbo")
        mount_path = str(base_path / disk.serial_number)
        filesystem_type = "ext4" if mode == DiskPreparationMode.DEDICATED_BACKUP else (
            disk.filesystem_type or "existing"
        )
        return DiskPreparationAgentResult(
            ok=True,
            mount_path=mount_path,
            filesystem_type=filesystem_type,
            message=(
                "Stub agent boundary: would prepare, mount, and persist this disk under "
                f"{mount_path} using mode {mode.value}."
            ),
        )


def get_disk_preparation_agent_bridge() -> DiskPreparationAgentBridge:
    return DiskPreparationAgentBridge()
