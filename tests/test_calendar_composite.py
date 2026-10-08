from datetime import UTC, datetime, timedelta

import pytest

from alladin.challenge.calendar_composite import CoveragePlan, SourceRequirement, compose_calendar
from alladin.challenge.economic_calendar import CalendarBatch, CalendarRevision
from alladin.challenge.event_policy import EventPolicy

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)


def plan():
    return CoveragePlan(
        id="fixture",
        version="1",
        source_url="https://example.test/coverage",
        requirements=(
            SourceRequirement(source="a", symbols=frozenset({"EURUSD"})),
            SourceRequirement(source="b", symbols=frozenset({"EURUSD", "XAUUSD"})),
        ),
    )


def batch(source="a", **updates):
    values = dict(
        source=source,
        source_url=f"https://example.test/{source}",
        licence="synthetic",
        observed_at=NOW - timedelta(minutes=1),
        valid_until=NOW + timedelta(hours=1),
        coverage_complete=True,
        document_sha256="a" * 64,
        coverage_start=NOW - timedelta(hours=1),
        coverage_end=NOW + timedelta(hours=1),
        revisions=(),
    )
    values.update(updates)
    return CalendarBatch(**values)


def compose(*batches, **updates):
    return compose_calendar(tuple(batches), plan=plan(), symbol="EURUSD", now=NOW, **updates)


def test_complete_composition_and_source_evidence():
    result = compose(batch(), batch("b"))
    assert result.snapshot.coverage_complete is True
    assert len(result.batch_sha256) == 2 and not result.gaps
    assert (
        EventPolicy().evaluate(symbol="EURUSD", now=NOW, snapshot=result.snapshot, restrict_news=True).reason
        == "CALENDAR_CLEAR"
    )
    assert compose(batch("b"), batch()) == result


@pytest.mark.parametrize(
    "updates,reason",
    [
        ({"coverage_complete": False}, "COVERAGE_UNVERIFIED"),
        ({"coverage_complete": None}, "COVERAGE_UNVERIFIED"),
        ({"valid_until": NOW - timedelta(seconds=1)}, "STALE"),
        ({"coverage_end": NOW + timedelta(seconds=899)}, "HORIZON_INSUFFICIENT"),
        ({"coverage_start": NOW - timedelta(seconds=119)}, "HORIZON_INSUFFICIENT"),
        ({"document_sha256": None}, "DOCUMENT_HASH_MISSING"),
        ({"coverage_start": None, "coverage_end": None}, "HORIZON_INSUFFICIENT"),
    ],
)
def test_partial_or_unavailable_component_never_upgraded(updates, reason):
    result = compose(batch(**updates), batch("b"))
    assert result.snapshot.coverage_complete is False
    assert f"a:{reason}" in result.gaps
    assert (
        EventPolicy()
        .evaluate(symbol="EURUSD", now=NOW, snapshot=result.snapshot, restrict_news=True)
        .verdict.value
        == "BLOCK"
    )


def test_newest_stale_does_not_fall_back_and_future_ignored():
    old = batch(observed_at=NOW - timedelta(hours=2), valid_until=NOW + timedelta(hours=1))
    stale = batch(valid_until=NOW - timedelta(seconds=1))
    future = batch(observed_at=NOW + timedelta(minutes=1), valid_until=NOW + timedelta(hours=2))
    result = compose(old, stale, future, batch("b"))
    assert "a:STALE" in result.gaps
    assert result == compose(old, stale, batch("b"))


def test_missing_sources_and_unknown_symbols():
    assert compose(batch()).gaps == ("b:MISSING",)
    assert compose().snapshot.coverage_complete is False
    result = compose_calendar((batch(),), plan=plan(), symbol="BTCUSD", now=NOW)
    assert result.gaps == ("SYMBOL_UNCOVERED",)


def test_colliding_ids_are_source_qualified_and_causal():
    row = CalendarRevision(
        event_id="CPI",
        revision=1,
        release_at=NOW,
        known_at=NOW - timedelta(minutes=2),
        collected_at=NOW - timedelta(minutes=1),
        original_timezone="UTC",
        currency="USD",
        impacted_symbols=frozenset({"EURUSD"}),
        restricted=True,
    )
    result = compose(batch(revisions=(row,)), batch("b", revisions=(row,)))
    assert len(result.snapshot.events) == 2
    decision = EventPolicy().evaluate(symbol="EURUSD", now=NOW, snapshot=result.snapshot, restrict_news=True)
    assert decision.event_ids == ('["a","CPI"]', '["b","CPI"]')


def test_coverage_schema_rejected():
    with pytest.raises(ValueError):
        batch(coverage_end=None)
    with pytest.raises(ValueError):
        batch(coverage_start=NOW + timedelta(days=1))
    with pytest.raises(ValueError):
        SourceRequirement(source="a", symbols=frozenset({"eurusd"}))
    with pytest.raises(ValueError):
        SourceRequirement(source="a", symbols=frozenset({"EURUSD"}), lookahead_seconds=120)
    with pytest.raises(ValueError):
        compose(batch(), batch())
