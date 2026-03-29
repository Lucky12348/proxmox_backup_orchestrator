from fastapi import APIRouter

from app.api.dependencies import DbSession
from app.schemas import DiskPlanningRead, PlanningOverviewRead, UnplannedAssetRead
from app.services.planning import get_disk_planning, get_planning_overview, get_unplanned_assets


router = APIRouter(prefix="/planning", tags=["planning"])


@router.get("/disks", response_model=list[DiskPlanningRead])
def get_planning_disks(db: DbSession) -> list[DiskPlanningRead]:
    return [DiskPlanningRead(**summary.__dict__) for summary in get_disk_planning(db)]


@router.get("/unplanned-assets", response_model=list[UnplannedAssetRead])
def get_unplanned(db: DbSession) -> list[UnplannedAssetRead]:
    return [
        UnplannedAssetRead(
            vm_id=vm.id,
            name=vm.name,
            vm_type=vm.vm_type,
            size_gb=vm.size_gb,
            critical=vm.critical,
        )
        for vm in get_unplanned_assets(db)
    ]


@router.get("/overview", response_model=PlanningOverviewRead)
def get_overview(db: DbSession) -> PlanningOverviewRead:
    return PlanningOverviewRead(**get_planning_overview(db).__dict__)
