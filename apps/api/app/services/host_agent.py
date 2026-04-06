from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings, get_settings


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
    def __init__(self, *, base_url: str, token: str, timeout_seconds: float, label: str) -> None:
        self.base_url = base_url
        self.token = token
        self.timeout_seconds = timeout_seconds
        self.label = label

    def get_health(self) -> dict[str, Any]:
        result = self._request("GET", "/health")
        return result.payload

    def post(self, path: str, payload: dict[str, Any]) -> HostAgentResult:
        return self._request("POST", path, payload)

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> HostAgentResult:
        base_url = self.base_url.rstrip("/")
        url = f"{base_url}{path}"
        headers = {"X-Agent-Token": self.token}

        try:
            with httpx.Client(timeout=self.timeout_seconds, headers=headers) as client:
                response = client.request(method, url, json=payload)
        except httpx.TimeoutException as exc:
            raise HostAgentError(
                f"{self.label} request timed out after {self.timeout_seconds} seconds: `{method} {url}`.",
                stdout_log=None,
                stderr_log=str(exc),
                command_summary=f"{method} {url}",
                execution_cwd=None,
                return_code=None,
            ) from exc
        except httpx.HTTPError as exc:
            raise HostAgentError(
                f"{self.label} request failed: `{method} {url}`.",
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
    settings = get_settings()
    return _build_agent_client(
        settings,
        base_url=settings.host_agent_base_url,
        token=settings.host_agent_token,
        timeout_seconds=settings.host_agent_timeout_seconds,
        label="Host agent",
    )


def get_pbs_agent_client() -> HostAgentClient:
    settings = get_settings()
    return _build_agent_client(
        settings,
        base_url=settings.pbs_agent_base_url,
        token=settings.pbs_agent_token,
        timeout_seconds=settings.pbs_agent_timeout_seconds,
        label="PBS agent",
    )


def _build_agent_client(
    settings: Settings,
    *,
    base_url: str,
    token: str,
    timeout_seconds: float,
    label: str,
) -> HostAgentClient:
    return HostAgentClient(
        base_url=base_url,
        token=token,
        timeout_seconds=timeout_seconds,
        label=label,
    )
