from collections.abc import Mapping

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

    def _get(self, path: str) -> list[dict] | dict:
        if not self.settings.pve_api_token_id or not self.settings.pve_api_token_secret:
            raise RuntimeError("Proxmox API token credentials are not configured")

        with httpx.Client(
            base_url=self.settings.pve_api_url.rstrip("/") + "/",
            headers=self.headers,
            verify=self.settings.pve_verify_ssl,
            timeout=20.0,
        ) as client:
            response = client.get(path.lstrip("/"))
            response.raise_for_status()
            payload = response.json()

        return payload.get("data", payload)

    def get_cluster_status(self) -> list[dict]:
        data = self._get("cluster/status")
        return data if isinstance(data, list) else [data]

    def list_qemu_vms(self, node_name: str) -> list[dict]:
        data = self._get(f"nodes/{node_name}/qemu")
        return data if isinstance(data, list) else []

    def list_lxc_containers(self, node_name: str) -> list[dict]:
        data = self._get(f"nodes/{node_name}/lxc")
        return data if isinstance(data, list) else []
