import logging

import httpx
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.dependencies import DbSession
from app.core.config import get_settings
from app.models import VirtualMachine
from app.schemas import ProxmoxBackupJobRead, ProxmoxBackupJobSelectionUpdate
from app.services.asset_ignores import get_asset_ignore_map, is_vm_ignored
from app.services.proxmox_client import (
    ProxmoxClient,
    is_include_selected_backup_job,
    parse_backup_job_vmids,
)
from app.services.sync_state import run_proxmox_sync_guarded


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/proxmox", tags=["proxmox"])


@router.get("/backup-jobs", response_model=list[ProxmoxBackupJobRead])
def list_backup_jobs(db: DbSession) -> list[ProxmoxBackupJobRead]:
    client = ProxmoxClient(get_settings())
    try:
        jobs = client.list_backup_jobs()
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Proxmox API failed: {exc}") from exc

    return [_job_to_read(job, db) for job in jobs]


@router.patch("/backup-jobs/{job_id}/selection", response_model=ProxmoxBackupJobRead)
def update_backup_job_selection(
    job_id: str,
    payload: ProxmoxBackupJobSelectionUpdate,
    db: DbSession,
) -> ProxmoxBackupJobRead:
    client = ProxmoxClient(get_settings())
    try:
        current = client.get_backup_job(job_id)
        if not current:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proxmox backup job not found")
        if not is_include_selected_backup_job(current):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Mode de selection non supporte pour modification dans PBO.",
            )

        before = parse_backup_job_vmids(current)
        after = sorted(set(payload.selected_vmids))
        logger.info("proxmox_backup_job_selection_update job_id=%s before=%s after=%s", job_id, before, after)
        client.update_backup_job_selection(job_id, after)
        try:
            run_proxmox_sync_guarded()
        except Exception as exc:
            logger.warning("proxmox sync after backup job update failed safely: %s", exc)
        updated = client.get_backup_job(job_id)
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Proxmox API rejected update: {exc}") from exc

    return _job_to_read(updated, db)


def _job_to_read(job: dict, db: DbSession) -> ProxmoxBackupJobRead:
    selected_vmids = parse_backup_job_vmids(job)
    supported = is_include_selected_backup_job(job)
    assets = list(
        db.scalars(
            select(VirtualMachine)
            .where(VirtualMachine.source == "proxmox", VirtualMachine.external_id.is_not(None))
            .order_by(VirtualMachine.name.asc())
        )
    )
    ignore_map = get_asset_ignore_map(db, assets)
    selected = set(selected_vmids)
    included_assets = []
    available_assets = []
    for vm in assets:
        try:
            vmid = int(vm.external_id or vm.id)
        except ValueError:
            continue
        payload = {
            "vmid": vmid,
            "name": vm.name,
            "vm_type": vm.vm_type.value,
            "node": vm.node_name,
            "included": vmid in selected,
            "ignored": is_vm_ignored(vm, ignore_map),
        }
        if vmid in selected:
            included_assets.append(payload)
        else:
            available_assets.append(payload)

    return ProxmoxBackupJobRead(
        job_id=str(job.get("id") or job.get("job_id") or ""),
        enabled=not _truthy_disabled(job.get("enabled")),
        node=job.get("node"),
        schedule=job.get("schedule"),
        storage=job.get("storage"),
        retention=_format_retention(job.get("prune-backups") or job.get("retention")),
        selection_mode="include_selected_vms" if supported else "unsupported",
        selected_vmids=selected_vmids,
        comment=job.get("comment"),
        next_run=str(job.get("next-run") or job.get("next_run") or "") or None,
        supported=supported,
        unsupported_reason=None if supported else "Mode de selection non supporte pour modification dans PBO.",
        included_assets=included_assets,
        available_assets=available_assets,
    )


def _truthy_disabled(value) -> bool:
    return str(value).lower() in {"0", "false", "no"}


def _format_retention(value: object) -> str | None:
    """Normalize a PVE `prune-backups` value to a display string.

    The Proxmox API returns this field as a plain string when the property
    string has a single component, but expands it to a dict (one entry per
    keep-* rule) when it has more than one — e.g. `{"keep-last": "4",
    "keep-monthly": "8"}`. `ProxmoxBackupJobRead.retention` is a plain string,
    so a dict here must be joined back into PVE's own `key=value,...` format
    (sorted for a stable, deterministic display) instead of being passed
    through as-is.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return ",".join(f"{key}={value[key]}" for key in sorted(value))
    return str(value)
