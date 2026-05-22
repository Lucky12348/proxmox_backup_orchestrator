from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, TypeVar

import httpx

from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.services.pbs_sync import PBSSyncSummary, sync_pbs_inventory
from app.services.proxmox_sync import ProxmoxSyncSummary, sync_proxmox_inventory


@dataclass
class IntegrationSyncState:
    last_sync_at: datetime | None = None
    sync_running: bool = False
    last_error: str | None = None


_proxmox_state = IntegrationSyncState()
_pbs_state = IntegrationSyncState()
_proxmox_lock = threading.Lock()
_pbs_lock = threading.Lock()
T = TypeVar("T")


def get_proxmox_sync_state() -> IntegrationSyncState:
    return _proxmox_state


def get_pbs_sync_state() -> IntegrationSyncState:
    return _pbs_state


def run_proxmox_sync_guarded() -> ProxmoxSyncSummary | None:
    return _run_guarded(_proxmox_lock, _proxmox_state, _sync_proxmox)


def run_pbs_sync_guarded() -> PBSSyncSummary | None:
    return _run_guarded(_pbs_lock, _pbs_state, _sync_pbs)


def trigger_auto_sync_if_stale(settings: Settings | None = None) -> dict[str, bool | IntegrationSyncState]:
    current_settings = settings or get_settings()
    if not current_settings.auto_sync_enabled:
        return {"enabled": False, "proxmox_triggered": False, "pbs_triggered": False}

    proxmox_triggered = _start_if_stale(
        _proxmox_lock,
        _proxmox_state,
        current_settings.proxmox_sync_interval_seconds,
        run_proxmox_sync_guarded,
    )
    pbs_triggered = _start_if_stale(
        _pbs_lock,
        _pbs_state,
        current_settings.pbs_sync_interval_seconds,
        run_pbs_sync_guarded,
    )
    return {
        "enabled": True,
        "proxmox_triggered": proxmox_triggered,
        "pbs_triggered": pbs_triggered,
    }


def _start_if_stale(
    lock: threading.Lock,
    state: IntegrationSyncState,
    interval_seconds: int,
    target: Callable[[], object],
) -> bool:
    with lock:
        if state.sync_running:
            return False
        if state.last_sync_at is not None:
            age = datetime.utcnow() - state.last_sync_at
            if age < timedelta(seconds=interval_seconds):
                return False

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return True


def _run_guarded(
    lock: threading.Lock,
    state: IntegrationSyncState,
    action: Callable[[], T],
) -> T | None:
    with lock:
        if state.sync_running:
            return None
        state.sync_running = True
        state.last_error = None

    try:
        summary = action()
    except (RuntimeError, httpx.HTTPError) as exc:
        with lock:
            state.last_error = str(exc)
        raise
    except Exception as exc:
        with lock:
            state.last_error = str(exc)
        raise
    else:
        with lock:
            state.last_sync_at = datetime.utcnow()
            state.last_error = None
        return summary
    finally:
        with lock:
            state.sync_running = False


def _sync_proxmox() -> ProxmoxSyncSummary:
    with SessionLocal() as db:
        return sync_proxmox_inventory(db)


def _sync_pbs() -> PBSSyncSummary:
    with SessionLocal() as db:
        return sync_pbs_inventory(db)
