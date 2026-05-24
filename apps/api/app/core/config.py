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
    notifications_enabled: bool = parse_bool(os.getenv("NOTIFICATIONS_ENABLED"), default=False)
    ntfy_base_url: str = os.getenv("NTFY_BASE_URL", "https://ntfy.sh")
    ntfy_topic: str = os.getenv("NTFY_TOPIC", "")
    ntfy_username: str = os.getenv("NTFY_USERNAME", "")
    ntfy_password: str = os.getenv("NTFY_PASSWORD", "")
    notify_on_backup_success: bool = parse_bool(os.getenv("NOTIFY_ON_BACKUP_SUCCESS"), default=True)
    notify_on_backup_failure: bool = parse_bool(os.getenv("NOTIFY_ON_BACKUP_FAILURE"), default=True)
    notify_on_disk_eject_ready: bool = parse_bool(os.getenv("NOTIFY_ON_DISK_EJECT_READY"), default=True)
    notify_on_update_result: bool = parse_bool(os.getenv("NOTIFY_ON_UPDATE_RESULT"), default=True)
    notify_on_agent_degraded: bool = parse_bool(os.getenv("NOTIFY_ON_AGENT_DEGRADED"), default=True)
    notify_on_low_coverage: bool = parse_bool(os.getenv("NOTIFY_ON_LOW_COVERAGE"), default=True)
    low_coverage_threshold_percent: float = float(os.getenv("LOW_COVERAGE_THRESHOLD_PERCENT", "100"))
    pve_api_url: str = os.getenv(
        "PVE_API_URL",
        "https://proxmox.example.local:8006/api2/json",
    )
    pve_api_token_id: str = os.getenv("PVE_API_TOKEN_ID", "")
    pve_api_token_secret: str = os.getenv("PVE_API_TOKEN_SECRET", "")
    pve_verify_ssl: bool = parse_bool(os.getenv("PVE_VERIFY_SSL"), default=False)
    pve_node_name: str = os.getenv("PVE_NODE_NAME", "proxmox")
    pbs_execution_vm_id: int = int(os.getenv("PBS_EXECUTION_VM_ID", "100"))
    pbs_execution_vm_node: str = os.getenv("PBS_EXECUTION_VM_NODE", os.getenv("PVE_NODE_NAME", "proxmox"))
    pbs_api_url: str = os.getenv(
        "PBS_API_URL",
        "https://pbs.example.local:8007/api2/json",
    )
    pbs_token_id: str = os.getenv("PBS_TOKEN_ID", "")
    pbs_token_secret: str = os.getenv("PBS_TOKEN_SECRET", "")
    pbs_verify_ssl: bool = parse_bool(os.getenv("PBS_VERIFY_SSL"), default=False)
    pbs_datastore: str = os.getenv("PBS_DATASTORE", "backup-store")
    host_agent_base_url: str = os.getenv("HOST_AGENT_BASE_URL", "http://proxmox-host:8081")
    host_agent_token: str = os.getenv("HOST_AGENT_TOKEN", "")
    host_agent_timeout_seconds: float = float(os.getenv("HOST_AGENT_TIMEOUT_SECONDS", "7200"))
    pbs_agent_base_url: str = os.getenv("PBS_AGENT_BASE_URL", "http://pbs-host:8081")
    pbs_agent_token: str = os.getenv("PBS_AGENT_TOKEN", "")
    pbs_agent_timeout_seconds: float = float(os.getenv("PBS_AGENT_TIMEOUT_SECONDS", "7200"))
    external_backup_callback_base_url: str = os.getenv(
        "EXTERNAL_BACKUP_CALLBACK_BASE_URL",
        "http://api:8000/api/v1",
    )
    external_backup_legacy_coexistence_enabled: bool = parse_bool(
        os.getenv("EXTERNAL_BACKUP_LEGACY_COEXISTENCE_ENABLED"),
        default=False,
    )
    external_loop_datastore_size_gb: int = int(os.getenv("AGENT_LOOP_DATASTORE_SIZE_GB", "500"))
    agent_stale_after_minutes: int = int(os.getenv("AGENT_STALE_AFTER_MINUTES", "10"))
    show_seed_disks: bool = parse_bool(os.getenv("SHOW_SEED_DISKS"), default=False)
    auto_sync_enabled: bool = parse_bool(os.getenv("AUTO_SYNC_ENABLED"), default=True)
    proxmox_sync_interval_seconds: int = int(os.getenv("PROXMOX_SYNC_INTERVAL_SECONDS", "60"))
    pbs_sync_interval_seconds: int = int(os.getenv("PBS_SYNC_INTERVAL_SECONDS", "60"))
    maintenance_timeout_seconds: float = float(os.getenv("MAINTENANCE_TIMEOUT_SECONDS", "120"))
    app_maintenance_agent_base_url: str = os.getenv(
        "APP_MAINTENANCE_AGENT_BASE_URL",
        "http://127.0.0.1:8092",
    )
    app_maintenance_agent_token: str = os.getenv("APP_MAINTENANCE_AGENT_TOKEN", "")
    agent_repo_path: str = os.getenv("AGENT_REPO_PATH", os.getcwd())

    @property
    def cors_origins(self) -> list[str]:
        return [self.frontend_origin, self.frontend_origin_alt]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
