"""Validated offline calendar archive and causal replay, never a live provider.

Availability includes collection latency. Refreshes are complete snapshots, not
incremental patches: a missing event in a refresh is an explicit provider claim.
The adapter cannot certify provider coverage, licence or contractual rules.
"""
from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from alladin.challenge.event_policy import CalendarSnapshot, EconomicEvent


class CalendarRevision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    event_id: str = Field(min_length=1)
    revision: int = Field(ge=1, strict=True)
    release_at: AwareDatetime
    known_at: AwareDatetime
    collected_at: AwareDatetime
    original_timezone: str
    currency: str
    impacted_symbols: frozenset[str] = Field(min_length=1)
    restricted: bool = Field(strict=True)
    forecast: float | None = Field(default=None, strict=True)
    previous: float | None = Field(default=None, strict=True)
    actual: float | None = Field(default=None, strict=True)

    @field_validator("release_at", "known_at", "collected_at")
    @classmethod
    def utc_times(cls, value: datetime) -> datetime:
        if isinstance(value.tzinfo, ZoneInfo):
            roundtrip = value.astimezone(UTC).astimezone(value.tzinfo)
            if (roundtrip.replace(tzinfo=None), roundtrip.fold) != (value.replace(tzinfo=None), value.fold):
                raise ValueError("nonexistent or invalid local DST timestamp")
        return value.astimezone(UTC)

    @field_validator("event_id", "currency", "original_timezone")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError("nonblank, unpadded identity required")
        return value

    @field_validator("impacted_symbols")
    @classmethod
    def symbols_valid(cls, value: frozenset[str]) -> frozenset[str]:
        if any(not s.strip() or s != s.strip() for s in value):
            raise ValueError("ambiguous symbol")
        return value

    @model_validator(mode="after")
    def causal_timing(self) -> CalendarRevision:
        try:
            ZoneInfo(self.original_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("unknown original timezone") from exc
        if self.known_at > self.collected_at:
            raise ValueError("collection precedes availability")
        if self.actual is not None and self.known_at < self.release_at:
            raise ValueError("actual result precedes release")
        return self


class CalendarBatch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = Field(default=1, ge=1, le=1, strict=True)
    source: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    licence: str = Field(min_length=1)
    observed_at: AwareDatetime
    valid_until: AwareDatetime
    revisions: tuple[CalendarRevision, ...]
    coverage_complete: bool | None = Field(default=None, strict=True)
    document_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    coverage_start: AwareDatetime | None = None
    coverage_end: AwareDatetime | None = None

    @field_validator("observed_at", "valid_until")
    @classmethod
    def utc_times(cls, value: datetime) -> datetime:
        if isinstance(value.tzinfo, ZoneInfo):
            roundtrip = value.astimezone(UTC).astimezone(value.tzinfo)
            if (roundtrip.replace(tzinfo=None), roundtrip.fold) != (value.replace(tzinfo=None), value.fold):
                raise ValueError("nonexistent or invalid local DST timestamp")
        return value.astimezone(UTC)

    @field_validator("coverage_start", "coverage_end")
    @classmethod
    def utc_horizon(cls, value: datetime | None) -> datetime | None:
        return cls.utc_times(value) if value is not None else None

    @field_validator("source", "source_url", "licence")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError("source and licence must be explicit")
        return value

    @model_validator(mode="after")
    def validate_refresh(self) -> CalendarBatch:
        if self.valid_until < self.observed_at:
            raise ValueError("refresh expiry precedes observation")
        if (self.coverage_start is None) != (self.coverage_end is None):
            raise ValueError("both coverage horizon boundaries required")
        if self.coverage_start is not None and self.coverage_end is not None and self.coverage_end < self.coverage_start:
            raise ValueError("invalid coverage horizon")
        ids: set[tuple[str, int]] = set()
        latest: dict[str, CalendarRevision] = {}
        for row in sorted(self.revisions, key=lambda r: (r.event_id, r.revision)):
            key = row.event_id, row.revision
            if key in ids:
                raise ValueError("duplicate event revision")
            ids.add(key)
            if row.collected_at > self.observed_at:
                raise ValueError("refresh contains a future collection")
            previous = latest.get(row.event_id)
            if previous and (row.known_at <= previous.known_at or row.collected_at < previous.collected_at):
                raise ValueError("revision availability must progress monotonically")
            latest[row.event_id] = row
        return self

    def snapshot(self) -> CalendarSnapshot:
        latest: dict[str, CalendarRevision] = {}
        for row in sorted(self.revisions, key=lambda r: r.revision):
            latest[row.event_id] = row
        events = tuple(
            EconomicEvent(row.event_id, row.release_at.astimezone(UTC), row.impacted_symbols,
                          row.restricted, row.collected_at.astimezone(UTC))
            for _, row in sorted(latest.items())
        )
        return CalendarSnapshot(self.observed_at.astimezone(UTC), self.valid_until.astimezone(UTC),
                                self.source, events, self.coverage_complete)


def replay_calendar(batches: tuple[CalendarBatch, ...], *, now: datetime) -> CalendarSnapshot | None:
    """Choose the last *received* complete refresh; never fall back from stale.

    Equal refresh timestamps are ambiguous and rejected, including at restart.
    EventPolicy retains responsibility for rejecting an expired snapshot.
    """
    if now.utcoffset() is None:
        raise ValueError("replay clock must be timezone-aware")
    observed = [b.observed_at for b in batches]
    if len(set(observed)) != len(observed):
        raise ValueError("ambiguous refresh timestamps")
    candidates = [batch for batch in batches if batch.observed_at <= now]
    return max(candidates, key=lambda b: b.observed_at).snapshot() if candidates else None
