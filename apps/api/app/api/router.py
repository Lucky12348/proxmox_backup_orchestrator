from fastapi import APIRouter, Depends

from app.api.routes import (
    agent,
    backup_runs,
    disks,
    external_backups,
    integrations_pbs,
    integrations_proxmox,
    maintenance,
    overview,
    planning,
    system,
    vms,
)
from app.auth import get_current_user, router as auth_router


public_router = APIRouter(prefix="/api/v1")
public_router.include_router(auth_router)
public_router.include_router(agent.router)
public_router.include_router(external_backups.public_callback_router)

protected_router = APIRouter(
    prefix="/api/v1",
    dependencies=[Depends(get_current_user)],
)

protected_router.include_router(overview.router)
protected_router.include_router(vms.router)
protected_router.include_router(disks.router)
protected_router.include_router(external_backups.router)
protected_router.include_router(backup_runs.router)
protected_router.include_router(integrations_proxmox.router)
protected_router.include_router(integrations_pbs.router)
protected_router.include_router(planning.router)
protected_router.include_router(system.router)
protected_router.include_router(maintenance.router)

api_router = APIRouter()
api_router.include_router(public_router)
api_router.include_router(protected_router)
