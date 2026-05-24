from collections.abc import Mapping
from time import sleep
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import Settings, get_settings


class ProxmoxClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def headers(self) -> Mapping[str, str]:
        return {
            "Authorization": (
                f"PVEAPIToken={self.settings.pve_api_token_id}="
                f"{self.settings.pve_api_token_secret}"
            )
        }

    def _request(self, method: str, path: str, *, data: Mapping[str, Any] | None = None) -> Any:
        if not self.settings.pve_api_token_id or not self.settings.pve_api_token_secret:
            raise RuntimeError("Proxmox API token credentials are not configured")

        with httpx.Client(
            base_url=self.settings.pve_api_url.rstrip("/") + "/",
            headers=self.headers,
            verify=self.settings.pve_verify_ssl,
            timeout=20.0,
        ) as client:
            response = client.request(method, path.lstrip("/"), data=data)
            response.raise_for_status()
            payload = response.json()

        return payload.get("data", payload)

    def _get(self, path: str) -> Any:
        return self._request("GET", path)

    def _post(self, path: str, *, data: Mapping[str, Any] | None = None) -> Any:
        return self._request("POST", path, data=data)

    def _put(self, path: str, *, data: Mapping[str, Any] | None = None) -> Any:
        return self._request("PUT", path, data=data)

    def get_cluster_status(self) -> list[dict]:
        data = self._get("cluster/status")
        return data if isinstance(data, list) else [data]

    def list_qemu_vms(self, node_name: str) -> list[dict]:
        data = self._get(f"nodes/{node_name}/qemu")
        return data if isinstance(data, list) else []

    def list_lxc_containers(self, node_name: str) -> list[dict]:
        data = self._get(f"nodes/{node_name}/lxc")
        return data if isinstance(data, list) else []

    def list_usb_devices(self, node_name: str) -> list[dict]:
        data = self._get(f"nodes/{node_name}/hardware/usb")
        return data if isinstance(data, list) else []

    def list_backup_jobs(self) -> list[dict]:
        data = self._get("cluster/backup")
        return data if isinstance(data, list) else []

    def get_backup_job(self, job_id: str) -> dict:
        data = self._get(f"cluster/backup/{quote(job_id, safe='')}")
        return data if isinstance(data, dict) else {}

    def update_backup_job_selection(self, job_id: str, selected_vmids: list[int]) -> Any:
        current = self.get_backup_job(job_id)
        if not current:
            raise RuntimeError(f"Proxmox backup job `{job_id}` was not found")
        if not is_include_selected_backup_job(current):
            raise RuntimeError("Backup job selection mode is not supported for modification in PBO")

        data = {
            key: value
            for key, value in current.items()
            if key not in {"id", "digest", "next-run", "next_run"}
        }
        data["vmid"] = ",".join(str(vmid) for vmid in sorted(set(selected_vmids)))
        data["all"] = 0
        return self._put(f"cluster/backup/{quote(job_id, safe='')}", data=data)

    def get_qemu_config(self, node_name: str, vm_id: int) -> dict:
        data = self._get(f"nodes/{node_name}/qemu/{vm_id}/config")
        return data if isinstance(data, dict) else {}

    def set_qemu_usb_device(self, node_name: str, vm_id: int, slot: str, host_mapping: str, *, usb3: bool | None = None) -> Any:
        value = f"host={host_mapping}"
        if usb3 is not None:
            value = f"{value},usb3={1 if usb3 else 0}"
        response = self._put(
            f"nodes/{node_name}/qemu/{vm_id}/config",
            data={slot: value},
        )
        return self._wait_for_task_if_needed(node_name, response)

    def delete_qemu_usb_device(self, node_name: str, vm_id: int, slot: str) -> Any:
        response = self._put(
            f"nodes/{node_name}/qemu/{vm_id}/config",
            data={"delete": slot},
        )
        return self._wait_for_task_if_needed(node_name, response)

    def debug_set_delete_qemu_usb_device(self, node_name: str, vm_id: int, slot: str, host_mapping: str) -> dict[str, Any]:
        before = self.get_qemu_config(node_name, vm_id)
        set_response = self.set_qemu_usb_device(node_name, vm_id, slot, host_mapping)
        after_set = self.get_qemu_config(node_name, vm_id)
        delete_response = self.delete_qemu_usb_device(node_name, vm_id, slot)
        after_delete = self.get_qemu_config(node_name, vm_id)
        return {
            "before": before,
            "set_response": set_response,
            "after_set": after_set,
            "delete_response": delete_response,
            "after_delete": after_delete,
            "set_verified": slot in after_set,
            "delete_verified": slot not in after_delete,
        }

    def _wait_for_task_if_needed(self, node_name: str, response: Any) -> Any:
        upid = response if isinstance(response, str) and response.startswith("UPID:") else None
        if upid is None:
            return response

        quoted_upid = quote(upid, safe="")
        last_status: dict[str, Any] | None = None
        for _ in range(60):
            status_payload = self._get(f"nodes/{node_name}/tasks/{quoted_upid}/status")
            last_status = status_payload if isinstance(status_payload, dict) else {"raw": status_payload}
            if last_status.get("status") == "stopped":
                exit_status = str(last_status.get("exitstatus") or "")
                if exit_status == "OK":
                    return {"upid": upid, "task_status": last_status}
                task_log = self._get_task_log(node_name, quoted_upid)
                raise RuntimeError(
                    f"Proxmox task `{upid}` failed with exitstatus `{exit_status}`. "
                    f"Status: {last_status}. Log: {task_log}"
                )
            sleep(1)

        task_log = self._get_task_log(node_name, quoted_upid)
        raise RuntimeError(f"Timed out waiting for Proxmox task `{upid}`. Last status: {last_status}. Log: {task_log}")

    def _get_task_log(self, node_name: str, quoted_upid: str) -> Any:
        try:
            return self._get(f"nodes/{node_name}/tasks/{quoted_upid}/log")
        except Exception as exc:
            return f"Unable to fetch task log: {exc}"


def parse_backup_job_vmids(job: Mapping[str, Any]) -> list[int]:
    value = job.get("vmid")
    if value is None:
        return []
    if isinstance(value, (int, float)):
        return [int(value)]
    if isinstance(value, list):
        result: list[int] = []
        for item in value:
            try:
                result.append(int(item))
            except (TypeError, ValueError):
                continue
        return sorted(set(result))
    if isinstance(value, str):
        result = []
        for part in value.replace(";", ",").split(","):
            part = part.strip()
            if not part:
                continue
            try:
                result.append(int(part))
            except ValueError:
                continue
        return sorted(set(result))
    return []


def is_include_selected_backup_job(job: Mapping[str, Any]) -> bool:
    if str(job.get("all", "0")).lower() in {"1", "true", "yes"}:
        return False
    if job.get("pool") or job.get("exclude"):
        return False
    return bool(parse_backup_job_vmids(job))
