"""Causal macro surprise tests; no external provider required."""
from datetime import UTC, datetime, timedelta

import pytest

from alladin.challenge.economic_intelligence import (
    ConsensusObservation,
    EconomicRelease,
    assess_release,
)

T = datetime(2026, 10, 8, 12, tzinfo=UTC)


def release():
    return EconomicRelease("cpi", "CPI", 3.2, T, T + timedelta(seconds=3), "https://example.org/cpi")


def consensus(at=None):
    return ConsensusObservation("cpi", 2.8, at or T - timedelta(minutes=30), "https://example.org/forecast")


def test_release_waits_for_actual_receipt():
    assert assess_release(release(), consensus=consensus(), as_of=T).status == "NOT_YET_KNOWN"


def test_pre_release_consensus_and_surprise():
    result = assess_release(release(), consensus=consensus(), as_of=T + timedelta(seconds=4))
    assert result.status == "OBSERVED_SURPRISE"
    assert result.surprise == pytest.approx(0.4)
    assert result.relative_surprise == pytest.approx(0.4 / 2.8)


def test_no_post_release_lookahead():
    result = assess_release(release(), consensus=consensus(T + timedelta(seconds=1)),
                            as_of=T + timedelta(seconds=4))
    assert result.status == "CONSENSUS_NOT_PRE_RELEASE"
    assert result.surprise is None


def test_missing_consensus_stays_unknown():
    assert assess_release(release(), consensus=None, as_of=T + timedelta(seconds=4)).surprise is None


def test_rejects_naive_time_and_nonfinite_values():
    with pytest.raises(ValueError):
        EconomicRelease("cpi", "CPI", float("nan"), T, T, "https://example.org")
    with pytest.raises(ValueError):
        EconomicRelease("cpi", "CPI", 3.2, T.replace(tzinfo=None), T, "https://example.org")
