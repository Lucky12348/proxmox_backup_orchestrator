from dataclasses import dataclass

from app.models import ExternalDisk


@dataclass(frozen=True)
class AgentCommandResult:
    ok: bool
    message: str


class ExternalBackupAgentBridge:
    def prepare_external_datastore(self, disk: ExternalDisk, target_path: str) -> AgentCommandResult:
        mount_path = disk.mount_path or "<unknown>"
        return AgentCommandResult(
            ok=True,
            message=(
                "Stub agent boundary: would validate mount "
                f"{mount_path} and prepare target directory {target_path}."
            ),
        )

    def run_external_export(self, target_path: str, datastore_name: str) -> AgentCommandResult:
        return AgentCommandResult(
            ok=True,
            message=(
                "Stub export boundary: would run a PBS-native-like export for datastore "
                f"{datastore_name} into {target_path}."
            ),
        )


def get_external_backup_agent_bridge() -> ExternalBackupAgentBridge:
    return ExternalBackupAgentBridge()
