import logging

import httpx
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.dependencies import DbSession
from app.core.config import get_settings
from app.models import VirtualMachine
from app.schemas import ProxmoxBackupJobRead, ProxmoxBackupJobSelectionUpdate, ProxmoxBackupJobUpsert
from app.services.asset_ignores import get_asset_ignore_map, is_vm_ignored
from app.services.proxmox_client import (
    ProxmoxClient,
    flatten_pve_property_value,
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


@router.post("/backup-jobs", response_model=ProxmoxBackupJobRead, status_code=status.HTTP_201_CREATED)
def create_backup_job(payload: ProxmoxBackupJobUpsert, db: DbSession) -> ProxmoxBackupJobRead:
    if not payload.selected_vmids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Selectionnez au moins une VM/CT pour ce job.",
        )

    client = ProxmoxClient(get_settings())
    data = _build_backup_job_payload(payload)
    try:
        client.create_backup_job(data)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Proxmox API rejected creation: {exc}") from exc

    created = _find_job_by_signature(client, data)
    if created is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Job cree sur Proxmox mais introuvable ensuite pour confirmation. Verifie dans Proxmox directement.",
        )
    return _job_to_read(created, db)


@router.put("/backup-jobs/{job_id}", response_model=ProxmoxBackupJobRead)
def replace_backup_job(job_id: str, payload: ProxmoxBackupJobUpsert, db: DbSession) -> ProxmoxBackupJobRead:
    if not payload.selected_vmids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Selectionnez au moins une VM/CT pour ce job.",
        )

    client = ProxmoxClient(get_settings())
    try:
        current = client.get_backup_job(job_id)
        if not current:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proxmox backup job not found")
        client.replace_backup_job(job_id, _build_backup_job_payload(payload))
        updated = client.get_backup_job(job_id)
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Proxmox API rejected update: {exc}") from exc

    return _job_to_read(updated, db)


@router.delete("/backup-jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_backup_job(job_id: str) -> None:
    client = ProxmoxClient(get_settings())
    try:
        current = client.get_backup_job(job_id)
        if not current:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proxmox backup job not found")
        client.delete_backup_job(job_id)
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Proxmox API rejected deletion: {exc}") from exc


def _build_backup_job_payload(payload: ProxmoxBackupJobUpsert) -> dict[str, object]:
    data: dict[str, object] = {
        "storage": payload.storage,
        "schedule": payload.schedule,
        "mode": payload.mode,
        "enabled": 1 if payload.enabled else 0,
        "all": 0,
        "vmid": ",".join(str(vmid) for vmid in sorted(set(payload.selected_vmids))),
    }
    if payload.node:
        data["node"] = payload.node
    if payload.comment:
        data["comment"] = payload.comment
    retention = _build_retention_string(payload)
    if retention:
        data["prune-backups"] = retention
    return data


def _build_retention_string(payload: ProxmoxBackupJobUpsert) -> str | None:
    parts = [
        f"{key}={value}"
        for key, value in (
            ("keep-last", payload.keep_last),
            ("keep-daily", payload.keep_daily),
            ("keep-weekly", payload.keep_weekly),
            ("keep-monthly", payload.keep_monthly),
            ("keep-yearly", payload.keep_yearly),
        )
        if value is not None
    ]
    return ",".join(parts) if parts else None


def _find_job_by_signature(client: ProxmoxClient, submitted: dict[str, object]) -> dict | None:
    """Proxmox's `POST /cluster/backup` response doesn't reliably carry the
    new job's id across all PVE versions, so locate it by matching the
    schedule/storage/vmid we just submitted among the freshly listed jobs
    (there's no other stable handle to fetch the single record we created)."""
    for job in client.list_backup_jobs():
        if (
            job.get("schedule") == submitted.get("schedule")
            and job.get("storage") == submitted.get("storage")
            and str(job.get("vmid")) == str(submitted.get("vmid"))
        ):
            return job
    return None


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

    `ProxmoxBackupJobRead.retention` is a plain string, but the Proxmox API
    can return this field as a dict (see `flatten_pve_property_value`) — flatten
    it back for display instead of passing it through as-is.
    """
    if value is None:
        return None
    flattened = flatten_pve_property_value(value)
    return flattened if isinstance(flattened, str) else str(flattened)
