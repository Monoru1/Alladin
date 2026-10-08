"""Deterministic as-of macro event gate (DECISION-032).

Research / pre-execution building block, NOT connected to order submission.
The caller must provide a trusted, versioned calendar and firm profile.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum


class EventVerdict(StrEnum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    DEFER = "DEFER"


@dataclass(frozen=True)
class EconomicEvent:
    event_id: str
    release_at: datetime
    impacted_symbols: frozenset[str]
    restricted: bool = False
    published_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.event_id.strip() or self.release_at.utcoffset() is None:
            raise ValueError("event_id and timezone-aware release_at required")
        if not self.impacted_symbols or any(not s.strip() or s != s.strip() for s in self.impacted_symbols):
            raise ValueError("nonempty unambiguous impacted symbols required")
        if type(self.restricted) is not bool:
            raise ValueError("restricted must be boolean")
        if self.published_at is not None and self.published_at.utcoffset() is None:
            raise ValueError("published_at must be timezone-aware")
        object.__setattr__(self, "release_at", self.release_at.astimezone(UTC))
        if self.published_at is not None:
            object.__setattr__(self, "published_at", self.published_at.astimezone(UTC))


@dataclass(frozen=True)
class CalendarSnapshot:
    as_of: datetime
    valid_until: datetime
    source: str
    events: tuple[EconomicEvent, ...]

    def __post_init__(self) -> None:
        if self.as_of.utcoffset() is None or self.valid_until.utcoffset() is None:
            raise ValueError("timezone-aware snapshot required")
        object.__setattr__(self, "as_of", self.as_of.astimezone(UTC))
        object.__setattr__(self, "valid_until", self.valid_until.astimezone(UTC))
        if self.valid_until < self.as_of or not self.source.strip():
            raise ValueError("snapshot validity and source required")
        if len({e.event_id for e in self.events}) != len(self.events):
            raise ValueError("snapshot must contain one revision per event_id")


@dataclass(frozen=True)
class EventDecision:
    verdict: EventVerdict
    reason: str
    event_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class EventPolicy:
    pre_window: timedelta = timedelta(minutes=2)
    post_window: timedelta = timedelta(minutes=2)
    precaution_window: timedelta = timedelta(minutes=15)

    def __post_init__(self) -> None:
        if min(self.pre_window, self.post_window, self.precaution_window) < timedelta(0):
            raise ValueError("windows must be non-negative")

    def evaluate(
        self,
        *,
        symbol: str,
        now: datetime,
        snapshot: CalendarSnapshot | None,
        restrict_news: bool,
    ) -> EventDecision:
        """Fail closed on missing/stale/untrusted timing, including no calendar.

        `restrict_news` is supplied by a verified firm/account/phase profile;
        this module never guesses which firm rules apply.
        """
        if now.utcoffset() is None:
            return EventDecision(EventVerdict.BLOCK, "CLOCK_NOT_TIMEZONE_AWARE")
        now = now.astimezone(UTC)
        if snapshot is None:
            return EventDecision(EventVerdict.BLOCK, "CALENDAR_MISSING")
        if not snapshot.as_of <= now <= snapshot.valid_until:
            return EventDecision(EventVerdict.BLOCK, "CALENDAR_STALE_OR_FUTURE")
        matches = []
        for event in snapshot.events:
            if event.published_at is not None and event.published_at > now:
                continue  # no use of future revisions in causal replay
            if symbol.upper() not in {s.upper() for s in event.impacted_symbols}:
                continue
            matches.append(event)
        for event in matches:
            if (restrict_news and event.restricted and
                    event.release_at - self.pre_window <= now <= event.release_at + self.post_window):
                return EventDecision(EventVerdict.BLOCK, "FIRM_RESTRICTED_EVENT", (event.event_id,))
        for event in matches:
            if event.release_at - self.precaution_window <= now <= event.release_at + self.post_window:
                return EventDecision(EventVerdict.DEFER, "MACRO_VOLATILITY_WINDOW", (event.event_id,))
        return EventDecision(EventVerdict.ALLOW, "CALENDAR_CLEAR")
