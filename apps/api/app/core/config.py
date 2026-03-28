import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    app_name: str = "Proxmox Backup Orchestrator API"
    api_port: int = int(os.getenv("API_PORT", "8000"))
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@db:5432/proxmox_backup_orchestrator",
    )
    ntfy_base_url: str = os.getenv("NTFY_BASE_URL", "https://ntfy.sh")
    ntfy_topic: str = os.getenv("NTFY_TOPIC", "proxmox-backup-orchestrator")
    pve_api_url: str = os.getenv(
        "PVE_API_URL",
        "https://proxmox.example.local:8006/api2/json",
    )
    pbs_api_url: str = os.getenv(
        "PBS_API_URL",
        "https://pbs.example.local:8007/api2/json",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
