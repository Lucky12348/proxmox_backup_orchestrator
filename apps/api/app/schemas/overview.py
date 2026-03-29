from pydantic import BaseModel

from app.schemas.backup_run import BackupRunRead


class OverviewRead(BaseModel):
    total_vms: int
    protected_vms: int
    coverage_percent: float
    connected_disks: int
    latest_backup_status: str | None
    recent_backup_runs: list[BackupRunRead]
