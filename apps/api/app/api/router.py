from fastapi import APIRouter

from app.api.routes.agent import router as agent_router
from app.api.routes.backup_runs import router as backup_runs_router
from app.api.routes.disks import router as disks_router
from app.api.routes.external_backups import router as external_backups_router
from app.api.routes.integrations_pbs import router as integrations_pbs_router
from app.api.routes.integrations_proxmox import router as integrations_proxmox_router
from app.api.routes.overview import router as overview_router
from app.api.routes.planning import router as planning_router
from app.api.routes.vms import router as vms_router


api_router = APIRouter(prefix="/api/v1")
api_router.include_router(agent_router)
api_router.include_router(overview_router)
api_router.include_router(vms_router)
api_router.include_router(disks_router)
api_router.include_router(external_backups_router)
api_router.include_router(backup_runs_router)
api_router.include_router(integrations_proxmox_router)
api_router.include_router(integrations_pbs_router)
api_router.include_router(planning_router)
