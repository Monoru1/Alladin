"""Causal, passive economic surprise analysis; no trading decisions.

A release is visible only after both source publication and local receipt.
Consensus must have been received BEFORE the release; otherwise no surprise.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone-aware timestamp required")
    return value.astimezone(UTC)


@dataclass(frozen=True)
class EconomicRelease:
    event_id: str
    indicator: str
    actual: float
    published_at: datetime
    received_at: datetime
    source_url: str

    def __post_init__(self) -> None:
        if not self.event_id.strip() or not self.indicator.strip() or not self.source_url.startswith("https://"):
            raise ValueError("source and event identity required")
        if not isfinite(self.actual) or _utc(self.received_at) < _utc(self.published_at):
            raise ValueError("invalid release chronology/value")


@dataclass(frozen=True)
class ConsensusObservation:
    event_id: str
    expected: float
    received_at: datetime
    source_url: str

    def __post_init__(self) -> None:
        if not self.event_id.strip() or not self.source_url.startswith("https://") or not isfinite(self.expected):
            raise ValueError("invalid consensus")
        _utc(self.received_at)


@dataclass(frozen=True)
class EconomicAssessment:
    event_id: str
    status: str
    surprise: float | None
    relative_surprise: float | None


def assess_release(
    release: EconomicRelease, *, consensus: ConsensusObservation | None,
    as_of: datetime,
) -> EconomicAssessment:
    now = _utc(as_of)
    if max(_utc(release.published_at), _utc(release.received_at)) > now:
        return EconomicAssessment(release.event_id, "NOT_YET_KNOWN", None, None)
    if consensus is None or consensus.event_id != release.event_id:
        return EconomicAssessment(release.event_id, "CONSENSUS_UNAVAILABLE", None, None)
    if _utc(consensus.received_at) >= _utc(release.published_at):
        return EconomicAssessment(release.event_id, "CONSENSUS_NOT_PRE_RELEASE", None, None)
    if _utc(consensus.received_at) > now:
        return EconomicAssessment(release.event_id, "CONSENSUS_NOT_YET_KNOWN", None, None)
    surprise = release.actual - consensus.expected
    relative = surprise / abs(consensus.expected) if consensus.expected != 0 else None
    return EconomicAssessment(release.event_id, "OBSERVED_SURPRISE", surprise, relative)
