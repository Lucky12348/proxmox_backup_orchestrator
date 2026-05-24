from fastapi import APIRouter

from app.api.dependencies import DbSession
from app.schemas import AssetIgnoreRead, AssetIgnoreUpdate
from app.services.asset_ignores import list_asset_ignores, upsert_asset_ignore


router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("/ignore", response_model=list[AssetIgnoreRead])
def get_ignored_assets(db: DbSession) -> list:
    return list_asset_ignores(db)


@router.patch("/{source}/{node}/{vmid}/ignore", response_model=AssetIgnoreRead)
def update_asset_ignore(
    source: str,
    node: str,
    vmid: str,
    payload: AssetIgnoreUpdate,
    db: DbSession,
):
    return upsert_asset_ignore(
        db,
        source=source,
        node="" if node == "-" else node,
        vmid=vmid,
        ignored=payload.ignored,
        reason=payload.reason,
    )
