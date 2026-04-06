import os
from dataclasses import dataclass
from functools import lru_cache


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default

    return value.strip().lower() in {"1", "true", "yes", "on"}


def normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)

    return database_url


@dataclass(frozen=True)
class Settings:
    app_name: str = "Proxmox Backup Orchestrator API"
    app_env: str = os.getenv("APP_ENV", "development")
    api_port: int = int(os.getenv("API_PORT", "8000"))
    database_url: str = normalize_database_url(
        os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://postgres:postgres@db:5432/proxmox_backup_orchestrator",
        )
    )
    frontend_origin: str = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
    frontend_origin_alt: str = os.getenv("FRONTEND_ORIGIN_ALT", "http://127.0.0.1:5173")
    ntfy_base_url: str = os.getenv("NTFY_BASE_URL", "https://ntfy.sh")
    ntfy_topic: str = os.getenv("NTFY_TOPIC", "proxmox-backup-orchestrator")
    pve_api_url: str = os.getenv(
        "PVE_API_URL",
        "https://proxmox.example.local:8006/api2/json",
    )
    pve_api_token_id: str = os.getenv("PVE_API_TOKEN_ID", "")
    pve_api_token_secret: str = os.getenv("PVE_API_TOKEN_SECRET", "")
    pve_verify_ssl: bool = parse_bool(os.getenv("PVE_VERIFY_SSL"), default=False)
    pve_node_name: str = os.getenv("PVE_NODE_NAME", "proxmox")
    pbs_api_url: str = os.getenv(
        "PBS_API_URL",
        "https://pbs.example.local:8007/api2/json",
    )
    pbs_token_id: str = os.getenv("PBS_TOKEN_ID", "")
    pbs_token_secret: str = os.getenv("PBS_TOKEN_SECRET", "")
    pbs_verify_ssl: bool = parse_bool(os.getenv("PBS_VERIFY_SSL"), default=False)
    pbs_datastore: str = os.getenv("PBS_DATASTORE", "backup")
    host_agent_base_url: str = os.getenv("HOST_AGENT_BASE_URL", "http://proxmox-host:8081")
    host_agent_token: str = os.getenv("HOST_AGENT_TOKEN", "")
    host_agent_timeout_seconds: float = float(os.getenv("HOST_AGENT_TIMEOUT_SECONDS", "7200"))
    pbs_agent_base_url: str = os.getenv("PBS_AGENT_BASE_URL", "http://pbs-host:8081")
    pbs_agent_token: str = os.getenv("PBS_AGENT_TOKEN", "")
    pbs_agent_timeout_seconds: float = float(os.getenv("PBS_AGENT_TIMEOUT_SECONDS", "7200"))
    agent_stale_after_minutes: int = int(os.getenv("AGENT_STALE_AFTER_MINUTES", "10"))

    @property
    def cors_origins(self) -> list[str]:
        return [self.frontend_origin, self.frontend_origin_alt]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
