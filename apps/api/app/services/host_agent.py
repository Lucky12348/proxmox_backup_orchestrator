from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import get_settings


MAX_LOG_LENGTH = 32000


@dataclass(frozen=True)
class HostAgentResult:
    ok: bool
    message: str
    stdout_log: str | None
    stderr_log: str | None
    command_summary: str | None
    execution_cwd: str | None
    return_code: int | None
    payload: dict[str, Any]


class HostAgentError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        stdout_log: str | None,
        stderr_log: str | None,
        command_summary: str | None,
        execution_cwd: str | None,
        return_code: int | None,
    ) -> None:
        super().__init__(message)
        self.stdout_log = stdout_log
        self.stderr_log = stderr_log
        self.command_summary = command_summary
        self.execution_cwd = execution_cwd
        self.return_code = return_code


class HostAgentClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    def get_health(self) -> dict[str, Any]:
        result = self._request("GET", "/health")
        return result.payload

    def post(self, path: str, payload: dict[str, Any]) -> HostAgentResult:
        return self._request("POST", path, payload)

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> HostAgentResult:
        base_url = self.settings.host_agent_base_url.rstrip("/")
        url = f"{base_url}{path}"
        headers = {"X-Agent-Token": self.settings.host_agent_token}

        try:
            with httpx.Client(timeout=self.settings.host_agent_timeout_seconds, headers=headers) as client:
                response = client.request(method, url, json=payload)
        except httpx.TimeoutException as exc:
            raise HostAgentError(
                f"Host agent request timed out after {self.settings.host_agent_timeout_seconds} seconds: `{method} {url}`.",
                stdout_log=None,
                stderr_log=str(exc),
                command_summary=f"{method} {url}",
                execution_cwd=None,
                return_code=None,
            ) from exc
        except httpx.HTTPError as exc:
            raise HostAgentError(
                f"Host agent request failed: `{method} {url}`.",
                stdout_log=None,
                stderr_log=str(exc),
                command_summary=f"{method} {url}",
                execution_cwd=None,
                return_code=None,
            ) from exc

        response_payload = _parse_json_payload(response)
        if response.is_success:
            return HostAgentResult(
                ok=bool(response_payload.get("ok", True)),
                message=str(response_payload.get("message") or "Host agent request completed."),
                stdout_log=_truncate_log(_optional_string(response_payload.get("stdout_log"))),
                stderr_log=_truncate_log(_optional_string(response_payload.get("stderr_log"))),
                command_summary=_optional_string(response_payload.get("command_summary")) or f"{method} {url}",
                execution_cwd=_optional_string(response_payload.get("execution_cwd")),
                return_code=_optional_int(response_payload.get("return_code")),
                payload=response_payload,
            )

        raise HostAgentError(
            _build_error_message(method, url, response, response_payload),
            stdout_log=_truncate_log(_optional_string(response_payload.get("stdout_log"))),
            stderr_log=_truncate_log(_optional_string(response_payload.get("stderr_log"))) or _truncate_log(response.text),
            command_summary=_optional_string(response_payload.get("command_summary")) or f"{method} {url}",
            execution_cwd=_optional_string(response_payload.get("execution_cwd")),
            return_code=_optional_int(response_payload.get("return_code")) or response.status_code,
        )


def _parse_json_payload(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _build_error_message(method: str, url: str, response: httpx.Response, payload: dict[str, Any]) -> str:
    message = _optional_string(payload.get("message")) or _optional_string(payload.get("detail"))
    if message:
        return f"{message} (HTTP {response.status_code}, `{method} {url}`)."
    return f"Host agent returned HTTP {response.status_code} for `{method} {url}`."


def _optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _truncate_log(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) <= MAX_LOG_LENGTH:
        return value
    return f"{value[:MAX_LOG_LENGTH]}\n...[truncated]"


def get_host_agent_client() -> HostAgentClient:
    return HostAgentClient()
