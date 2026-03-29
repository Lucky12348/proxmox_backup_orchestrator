from collections.abc import Mapping

import httpx

from app.core.config import Settings, get_settings


class PBSClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def _client(self) -> httpx.Client:
        if not self.settings.pbs_username or not self.settings.pbs_password:
            raise RuntimeError("PBS credentials are not configured")

        return httpx.Client(
            base_url=self.settings.pbs_api_url.rstrip("/") + "/",
            auth=(self.settings.pbs_username, self.settings.pbs_password),
            verify=self.settings.pbs_verify_ssl,
            timeout=20.0,
        )

    def _get(self, path: str) -> list[dict] | dict:
        with self._client() as client:
            response = client.get(path.lstrip("/"))
            response.raise_for_status()
            payload = response.json()

        return payload.get("data", payload)

    def get_version(self) -> Mapping[str, str]:
        data = self._get("version")
        return data if isinstance(data, Mapping) else {}

    def list_datastores(self) -> list[dict]:
        data = self._get("config/datastore")
        return data if isinstance(data, list) else []

    def list_snapshots(self, datastore_name: str) -> list[dict]:
        data = self._get(f"admin/datastore/{datastore_name}/snapshots")
        return data if isinstance(data, list) else []
