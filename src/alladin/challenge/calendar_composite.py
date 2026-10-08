"""Causal multi-source composition. Coverage is an explicit input claim, never inferred."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from alladin.challenge.economic_calendar import CalendarBatch, replay_calendar
from alladin.challenge.event_policy import CalendarSnapshot, EconomicEvent
from alladin.challenge.policy_serialization import evidence_sha256


class SourceRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source: str = Field(min_length=1)
    symbols: frozenset[str] = Field(min_length=1)
    lookback_seconds: int = Field(default=120, strict=True, ge=120)
    lookahead_seconds: int = Field(default=900, strict=True, ge=900)

    @field_validator("source")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError("unambiguous source required")
        return value

    @field_validator("symbols")
    @classmethod
    def symbols_valid(cls, value: frozenset[str]) -> frozenset[str]:
        if any(not s.strip() or s != s.strip() or s != s.upper() for s in value):
            raise ValueError("canonical uppercase symbols required")
        return value


class CoveragePlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    requirements: tuple[SourceRequirement, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_sources(self) -> CoveragePlan:
        if len({r.source for r in self.requirements}) != len(self.requirements):
            raise ValueError("duplicate required source")
        return self


@dataclass(frozen=True)
class CompositeCalendar:
    snapshot: CalendarSnapshot
    plan_sha256: str
    batch_sha256: tuple[tuple[str, str], ...]
    gaps: tuple[str, ...]


def compose_calendar(
    batches: tuple[CalendarBatch, ...], *, plan: CoveragePlan, symbol: str, now: datetime
) -> CompositeCalendar:
    if now.utcoffset() is None or symbol != symbol.upper() or not symbol.strip() or symbol != symbol.strip():
        raise ValueError("aware clock and canonical symbol required")
    now = now.astimezone(UTC)
    required = tuple(r for r in plan.requirements if symbol in r.symbols)
    plan_sha = evidence_sha256(plan)
    gaps: list[str] = []
    evidence: list[tuple[str, str]] = []
    events: list[EconomicEvent] = []
    expires = now + timedelta(days=1)
    as_of = now
    if not required:
        gaps.append("SYMBOL_UNCOVERED")
    for requirement in sorted(required, key=lambda r: r.source):
        history = tuple(b for b in batches if b.source == requirement.source)
        snapshot = replay_calendar(history, now=now)
        if snapshot is None:
            gaps.append(f"{requirement.source}:MISSING")
            continue
        batch = max((b for b in history if b.observed_at <= now), key=lambda b: b.observed_at)
        evidence.append((batch.source, evidence_sha256(batch)))
        as_of = min(as_of, snapshot.as_of)
        expires = min(expires, snapshot.valid_until)
        if snapshot.valid_until < now:
            gaps.append(f"{batch.source}:STALE")
        if batch.coverage_complete is not True:
            gaps.append(f"{batch.source}:COVERAGE_UNVERIFIED")
        if (
            batch.coverage_start is None
            or batch.coverage_end is None
            or batch.coverage_start.astimezone(UTC) > now - timedelta(seconds=requirement.lookback_seconds)
            or batch.coverage_end.astimezone(UTC) < now + timedelta(seconds=requirement.lookahead_seconds)
        ):
            gaps.append(f"{batch.source}:HORIZON_INSUFFICIENT")
        if batch.document_sha256 is None:
            gaps.append(f"{batch.source}:DOCUMENT_HASH_MISSING")
        for event in snapshot.events:
            # A source without a symbol claim is not enough; off-scope events stay out.
            if symbol in event.impacted_symbols:
                # Source-qualified IDs avoid accidental cross-provider revision merging.
                identity = json.dumps([batch.source, event.event_id], separators=(",", ":"))
                events.append(
                    EconomicEvent(
                        identity,
                        event.release_at,
                        event.impacted_symbols,
                        event.restricted,
                        event.published_at,
                    )
                )
    digest = hashlib.sha256(
        json.dumps([plan_sha, evidence, sorted(gaps)], separators=(",", ":")).encode()
    ).hexdigest()
    # Missing/stale components retain explicit incomplete coverage. Do not create an
    # invalid date interval if one component expired before another was received.
    snapshot = CalendarSnapshot(
        min(as_of, expires),
        expires,
        f"composite:{digest}",
        tuple(sorted(events, key=lambda e: e.event_id)),
        not gaps,
    )
    return CompositeCalendar(snapshot, plan_sha, tuple(evidence), tuple(sorted(gaps)))
