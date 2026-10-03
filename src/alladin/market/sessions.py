"""Configured observation/entry windows; no inferred exchange opening hours."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SessionWindow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    start_minute: int = Field(ge=0, lt=1440)
    end_minute: int = Field(gt=0, le=1440)

    @model_validator(mode="after")
    def ordered(self) -> SessionWindow:
        if self.start_minute >= self.end_minute:
            raise ValueError("split overnight windows at midnight")
        return self


class SessionRules(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    timezone: str = "UTC"
    weekdays: frozenset[int] = frozenset(range(7))
    windows: tuple[SessionWindow, ...] = ()
    require_24_7: bool = False

    @model_validator(mode="after")
    def valid(self) -> SessionRules:
        ZoneInfo(self.timezone)
        if not self.weekdays or any(day < 0 or day > 6 for day in self.weekdays):
            raise ValueError("weekdays must contain integers 0..6")
        return self

    def allows(self, now: datetime, *, is_24_7: bool = False) -> bool:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("session clock must be timezone aware")
        if self.require_24_7 and not is_24_7:
            return False
        local = now.astimezone(ZoneInfo(self.timezone))
        minute = local.hour * 60 + local.minute
        return local.weekday() in self.weekdays and (
            not self.windows or any(w.start_minute <= minute < w.end_minute for w in self.windows)
        )
