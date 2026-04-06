from collections.abc import Mapping
from typing import Any

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

    def _request(self, method: str, path: str, *, data: Mapping[str, Any] | None = None) -> list[dict] | dict:
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

    def _get(self, path: str) -> list[dict] | dict:
        return self._request("GET", path)

    def _post(self, path: str, *, data: Mapping[str, Any] | None = None) -> list[dict] | dict:
        return self._request("POST", path, data=data)

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

    def get_qemu_config(self, node_name: str, vm_id: int) -> dict:
        data = self._get(f"nodes/{node_name}/qemu/{vm_id}/config")
        return data if isinstance(data, dict) else {}

    def set_qemu_usb_device(self, node_name: str, vm_id: int, slot: str, host_mapping: str) -> None:
        self._post(
            f"nodes/{node_name}/qemu/{vm_id}/config",
            data={slot: f"host={host_mapping}"},
        )

    def delete_qemu_usb_device(self, node_name: str, vm_id: int, slot: str) -> None:
        self._post(
            f"nodes/{node_name}/qemu/{vm_id}/config",
            data={"delete": slot},
        )
