from collections.abc import Mapping

import httpx

from app.core.config import Settings, get_settings


class PBSClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def headers(self) -> Mapping[str, str]:
        return {
            "Authorization": (
                f"PBSAPIToken={self.settings.pbs_token_id}:{self.settings.pbs_token_secret}"
            )
        }

    def _client(self) -> httpx.Client:
        if not self.settings.pbs_token_id or not self.settings.pbs_token_secret:
            raise RuntimeError("PBS API token credentials are not configured")

        return httpx.Client(
            base_url=self.settings.pbs_api_url.rstrip("/") + "/",
            headers=self.headers,
            verify=self.settings.pbs_verify_ssl,
            timeout=20.0,
        )

    def _get(self, path: str) -> list[dict] | dict:
        with self._client() as client:
            response = client.get(path.lstrip("/"))
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 401:
                    raise RuntimeError(
                        "PBS authentication failed. Check PBS token id/secret, token ACLs, "
                        "and datastore permissions."
                    ) from exc
                raise
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
