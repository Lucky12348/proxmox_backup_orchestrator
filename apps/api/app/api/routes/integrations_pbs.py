import httpx
from fastapi import APIRouter, HTTPException, status

from app.api.dependencies import DbSession
from app.core.config import get_settings
from app.schemas import PBSInventoryRead, PBSStatusRead, PBSSyncRead
from app.services.pbs_client import PBSClient
from app.services.pbs_sync import list_pbs_inventory
from app.services.sync_state import get_pbs_sync_state, run_pbs_sync_guarded


router = APIRouter(prefix="/integrations/pbs", tags=["integrations-pbs"])


@router.get("/status", response_model=PBSStatusRead)
def get_pbs_status() -> PBSStatusRead:
    settings = get_settings()
    client = PBSClient(settings)
    sync_state = get_pbs_sync_state()

    try:
        client.get_version()
    except RuntimeError as exc:
        return PBSStatusRead(
            connected=False,
            datastore=settings.pbs_datastore,
            verify_ssl=settings.pbs_verify_ssl,
            message=str(exc),
            last_sync_at=sync_state.last_sync_at,
            sync_running=sync_state.sync_running,
            last_sync_error=sync_state.last_error,
        )
    except httpx.HTTPError as exc:
        return PBSStatusRead(
            connected=False,
            datastore=settings.pbs_datastore,
            verify_ssl=settings.pbs_verify_ssl,
            message=f"Unable to reach PBS API: {exc}",
            last_sync_at=sync_state.last_sync_at,
            sync_running=sync_state.sync_running,
            last_sync_error=sync_state.last_error,
        )

    return PBSStatusRead(
        connected=True,
        datastore=settings.pbs_datastore,
        verify_ssl=settings.pbs_verify_ssl,
        message="Connection to PBS API succeeded",
        last_sync_at=sync_state.last_sync_at,
        sync_running=sync_state.sync_running,
        last_sync_error=sync_state.last_error,
    )


@router.post("/sync", response_model=PBSSyncRead)
def sync_pbs() -> PBSSyncRead:
    try:
        summary = run_pbs_sync_guarded()
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"PBS sync failed: {exc}",
        ) from exc

    if summary is None:
        return PBSSyncRead(
            matched_vms=0,
            matched_cts=0,
            total_snapshots_seen=0,
            already_running=True,
        )

    return PBSSyncRead(
        matched_vms=summary.matched_vms,
        matched_cts=summary.matched_cts,
        total_snapshots_seen=summary.total_snapshots_seen,
    )


@router.get("/inventory", response_model=list[PBSInventoryRead])
def get_pbs_inventory(db: DbSession) -> list[PBSInventoryRead]:
    return [
        PBSInventoryRead(
            vm_id=item.vm_id,
            name=item.name,
            vm_type=item.vm_type,
            last_backup_at=item.last_backup_at,
            protected=item.protected,
        )
        for item in list_pbs_inventory(db)
    ]
