from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, field_serializer


def utc_isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


class UTCDateTimeModel(BaseModel):
    @field_serializer("*", when_used="json")
    def serialize_datetimes(self, value: Any) -> Any:
        if isinstance(value, datetime):
            return utc_isoformat(value)
        return value
