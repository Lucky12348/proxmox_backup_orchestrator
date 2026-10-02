"""Schemas for the host-local ntfy notification engine managed through the Proxmox host agent.

Rules mirror `apps/agent/src/agent/ntfy_notif.py` (the agent re-validates
everything; this layer only rejects bad input before it leaves the app VM).
"""

import re
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator

from app.schemas.base import UTCDateTimeModel


EVENT_CODE_PATTERN = r"^[a-z0-9_]+(\.[a-z0-9_]+)*$"
EMOJI_PATTERN = r"^[a-z0-9_+-]{1,40}$"
TOPIC_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
VAR_KEY_PATTERN = r"^[A-Za-z0-9_]+$"
URL_MAX_LENGTH = 500

_EVENT_CODE_RE = re.compile(EVENT_CODE_PATTERN)
_VAR_KEY_RE = re.compile(VAR_KEY_PATTERN)


def _validate_optional_url(value: str | None) -> str | None:
    if value is None or value == "":
        return value
    parsed = urlparse(value)
    if (
        len(value) > URL_MAX_LENGTH
        or any(ch.isspace() for ch in value)
        or parsed.scheme not in {"http", "https"}
        or not parsed.netloc
    ):
        raise ValueError("must be empty or an http(s) URL")
    return value


def _reject_control_chars(value: str, *, allow_newline: bool) -> str:
    for ch in value:
        if ch == "\n" and allow_newline:
            continue
        if ord(ch) < 32 or ord(ch) == 127:
            raise ValueError("must not contain line breaks or control characters" if not allow_newline else "must not contain control characters")
    return value


class HostNotificationDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = Field(pattern=TOPIC_PATTERN)
    click: str | None = None
    icon: str | None = None
    late_after_sec: StrictInt | None = Field(default=None, ge=0, le=86400)

    _check_urls = field_validator("click", "icon")(_validate_optional_url)


class HostNotificationEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: StrictBool
    priority: StrictInt = Field(ge=1, le=5)
    emoji: str = Field(pattern=EMOJI_PATTERN)
    title: str = Field(min_length=1, max_length=60)
    message: str = Field(max_length=200)
    topic: str | None = Field(default=None, pattern=TOPIC_PATTERN)
    click: str | None = None
    icon: str | None = None

    _check_urls = field_validator("click", "icon")(_validate_optional_url)

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return _reject_control_chars(value, allow_newline=False)

    @field_validator("message")
    @classmethod
    def _message_chars(cls, value: str) -> str:
        return _reject_control_chars(value, allow_newline=True)


class HostNotificationTemplates(BaseModel):
    model_config = ConfigDict(extra="forbid")

    defaults: HostNotificationDefaults
    events: dict[str, HostNotificationEvent] = Field(max_length=200)

    @field_validator("events")
    @classmethod
    def _event_codes(cls, value: dict[str, HostNotificationEvent]) -> dict[str, HostNotificationEvent]:
        for code in value:
            if len(code) > 64 or not _EVENT_CODE_RE.match(code):
                raise ValueError(f"invalid event code `{code}`")
        return value

    def to_file_payload(self) -> dict[str, Any]:
        # Optional keys that were not provided stay absent from templates.json.
        return self.model_dump(exclude_none=True)


class HostNotificationTemplatesRead(UTCDateTimeModel):
    path: str | None = None
    modified_at: datetime | None = None
    backup_path: str | None = None
    templates: dict[str, Any]


class HostNotificationTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: str = Field(max_length=64, pattern=EVENT_CODE_PATTERN)
    vars: dict[str, str] = Field(default_factory=dict, max_length=20)

    @field_validator("vars")
    @classmethod
    def _vars(cls, value: dict[str, str]) -> dict[str, str]:
        for key, item in value.items():
            if not _VAR_KEY_RE.match(key):
                raise ValueError(f"invalid variable name `{key}`")
            if len(item) > 100:
                raise ValueError(f"variable `{key}`: at most 100 characters")
            _reject_control_chars(item, allow_newline=False)
        return value


class HostNotificationTestRead(BaseModel):
    ok: bool
    event: str
    return_code: int | None
    message: str
    stdout_log: str | None = None
    stderr_log: str | None = None


class HostNotificationHistoryEntry(BaseModel):
    ts: float | None
    event: str
    status: str
    title: str | None = None
    message: str | None = None


class HostNotificationHistoryRead(BaseModel):
    entries: list[HostNotificationHistoryEntry]
    skipped_lines: int = 0


class HostNotificationQueueRead(BaseModel):
    count: int
    oldest_ts: float | None = None
    oldest_age_seconds: int | None = None


HistoryStatus = Literal["queued", "sent", "muted"]


class ActivityEventRead(UTCDateTimeModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    category: str
    action: str
    status: str
    summary: str
    details: dict[str, Any] | None = None
