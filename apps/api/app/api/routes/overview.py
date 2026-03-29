from fastapi import APIRouter

from app.api.dependencies import DbSession
from app.schemas import OverviewRead
from app.schemas.backup_run import BackupRunRead
from app.services.overview import get_overview_metrics


router = APIRouter(tags=["overview"])


@router.get("/overview", response_model=OverviewRead)
def get_overview(db: DbSession) -> OverviewRead:
    metrics = get_overview_metrics(db)
    return OverviewRead(
        total_vms=metrics.total_vms,
        protected_vms=metrics.protected_vms,
        coverage_percent=metrics.coverage_percent,
        connected_disks=metrics.connected_disks,
        latest_backup_status=metrics.latest_backup_status,
        recent_backup_runs=[
            BackupRunRead.model_validate(run) for run in metrics.recent_backup_runs
        ],
    )
