from pydantic import BaseModel

from app.models import VMType


class DiskPlanningRead(BaseModel):
    disk_id: int
    serial_number: str
    display_name: str
    trusted: bool
    available_capacity_gb: int
    total_planned_gb: int
    planned_vm_count: int
    unplanned_vm_count: int
    fits_all: bool


class UnplannedAssetRead(BaseModel):
    vm_id: int
    name: str
    vm_type: VMType
    size_gb: int
    critical: bool


class PlanningOverviewRead(BaseModel):
    trusted_disk_count: int
    plannable_vm_count: int
    planned_vm_count: int
    planning_coverage_percent: float
