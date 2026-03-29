import httpx
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.dependencies import DbSession
from app.core.config import get_settings
from app.models import VirtualMachine
from app.schemas import ProxmoxStatusRead, ProxmoxSyncRead, VirtualMachineRead
from app.services.proxmox_client import ProxmoxClient
from app.services.proxmox_sync import sync_proxmox_inventory


router = APIRouter(prefix="/integrations/proxmox", tags=["integrations-proxmox"])


@router.get("/status", response_model=ProxmoxStatusRead)
def get_proxmox_status() -> ProxmoxStatusRead:
    settings = get_settings()
    client = ProxmoxClient(settings)

    try:
        client.get_cluster_status()
    except RuntimeError as exc:
        return ProxmoxStatusRead(
            connected=False,
            node_name=settings.pve_node_name,
            verify_ssl=settings.pve_verify_ssl,
            message=str(exc),
        )
    except httpx.HTTPError as exc:
        return ProxmoxStatusRead(
            connected=False,
            node_name=settings.pve_node_name,
            verify_ssl=settings.pve_verify_ssl,
            message=f"Unable to reach Proxmox API: {exc}",
        )

    return ProxmoxStatusRead(
        connected=True,
        node_name=settings.pve_node_name,
        verify_ssl=settings.pve_verify_ssl,
        message="Connection to Proxmox API succeeded",
    )


@router.post("/sync", response_model=ProxmoxSyncRead)
def sync_proxmox(db: DbSession) -> ProxmoxSyncRead:
    try:
        summary = sync_proxmox_inventory(db)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Proxmox sync failed: {exc}",
        ) from exc

    return ProxmoxSyncRead(
        synced_vms_count=summary.synced_vms_count,
        synced_cts_count=summary.synced_cts_count,
        total_seen=summary.total_seen,
    )


@router.get("/inventory", response_model=list[VirtualMachineRead])
def list_proxmox_inventory(db: DbSession) -> list[VirtualMachine]:
    return list(
        db.scalars(
            select(VirtualMachine)
            .where(VirtualMachine.source == "proxmox")
            .order_by(VirtualMachine.name.asc())
        )
    )
