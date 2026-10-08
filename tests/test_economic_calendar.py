"""Causal refreshes, delayed release data, malformed payloads and DST."""
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from alladin.challenge.economic_calendar import CalendarBatch, CalendarRevision, replay_calendar
from alladin.challenge.event_policy import EventPolicy, EventVerdict

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)


def row(**updates):
    data = dict(event_id="CPI", revision=1, release_at=NOW,
                known_at=NOW-timedelta(days=1), collected_at=NOW-timedelta(minutes=1),
                original_timezone="America/New_York", currency="USD",
                impacted_symbols=["EURUSD", "XAUUSD", "US100.cash"], restricted=True,
                forecast=3.1, previous=3.0)
    data.update(updates)
    return data


def batch(**updates):
    data = dict(source="synthetic", source_url="https://example.test/calendar",
                licence="synthetic test data", observed_at=NOW-timedelta(seconds=30),
                valid_until=NOW+timedelta(minutes=10), revisions=[row()])
    data.update(updates)
    return CalendarBatch.model_validate(data)


def test_restart_round_trip_and_delayed_schedule_revision():
    initial = batch()
    revised = batch(observed_at=NOW+timedelta(minutes=3), revisions=[row(), row(
        revision=2, release_at=NOW+timedelta(hours=1), known_at=NOW,
        collected_at=NOW+timedelta(minutes=3))])
    archive = tuple(CalendarBatch.model_validate_json(b.model_dump_json()) for b in (initial, revised))
    before = replay_calendar(archive, now=NOW)
    after = replay_calendar(archive, now=NOW+timedelta(minutes=3))
    assert before.events[0].release_at == NOW
    assert after.events[0].release_at == NOW+timedelta(hours=1)
    assert EventPolicy().evaluate(symbol="US100.cash", now=NOW, snapshot=before, restrict_news=True).verdict == EventVerdict.BLOCK
    assert replay_calendar(archive, now=NOW-timedelta(days=2)) is None


def test_actual_is_unavailable_until_collected_and_refresh_received():
    initial = batch()
    published = batch(observed_at=NOW+timedelta(seconds=20), revisions=[row(), row(
        revision=2, known_at=NOW, collected_at=NOW+timedelta(seconds=15), actual=3.4)])
    assert initial.revisions[0].actual is None
    assert replay_calendar((initial, published), now=NOW+timedelta(seconds=19)) == initial.snapshot()
    assert replay_calendar((initial, published), now=NOW+timedelta(seconds=20)) == published.snapshot()
    assert published.revisions[-1].actual == 3.4


@pytest.mark.parametrize("changes", [
    {"known_at": NOW+timedelta(seconds=1)}, {"release_at": NOW.replace(tzinfo=None)},
    {"event_id": " "}, {"original_timezone": "Mars/Foo"}, {"forecast": float("nan")},
    {"actual": float("inf")}, {"actual": 3.4}, {"revision": True}, {"restricted": "false"},
    {"impacted_symbols": []}, {"unexpected": 1},
])
def test_bad_rows_rejected(changes):
    with pytest.raises(ValidationError):
        CalendarRevision.model_validate(row(**changes))


@pytest.mark.parametrize("changes", [
    {"source": " "}, {"licence": " "}, {"schema_version": 2},
    {"valid_until": NOW-timedelta(days=1)}, {"revisions": [row(), row()]},
    {"revisions": [row(collected_at=NOW)]},
    {"revisions": [row(), row(revision=2)]},
])
def test_invalid_refreshes_rejected(changes):
    with pytest.raises(ValidationError):
        batch(**changes)


def test_latest_stale_refresh_never_falls_back_to_older_valid_one():
    old = batch(valid_until=NOW+timedelta(days=1))
    new = batch(observed_at=NOW, valid_until=NOW+timedelta(seconds=1))
    snapshot = replay_calendar((new, old), now=NOW+timedelta(seconds=2))
    d = EventPolicy().evaluate(symbol="EURUSD", now=NOW+timedelta(seconds=2), snapshot=snapshot, restrict_news=True)
    assert d.reason == "CALENDAR_STALE_OR_FUTURE"
    with pytest.raises(ValueError, match="ambiguous"):
        replay_calendar((old, old), now=NOW)


@pytest.mark.parametrize("fold", [0, 1])
def test_dst_repeated_hour_has_distinct_utc_instants(fold):
    release = datetime(2026, 11, 1, 1, 30, tzinfo=ZoneInfo("America/New_York"), fold=fold)
    received = release.astimezone(UTC)-timedelta(minutes=1)
    b = batch(observed_at=received, valid_until=received+timedelta(hours=1), revisions=[row(
        release_at=release, known_at=received, collected_at=received)])
    assert b.snapshot().events[0].release_at.hour == 5+fold
    assert EventPolicy().evaluate(symbol="XAUUSD", now=release.astimezone(UTC), snapshot=b.snapshot(), restrict_news=True).verdict == EventVerdict.BLOCK


def test_dst_fold_cannot_disguise_future_collection():
    zone = ZoneInfo("America/New_York")
    earlier = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=0)
    later = datetime(2026, 11, 1, 1, 15, tzinfo=zone, fold=1)
    with pytest.raises(ValidationError, match="future collection"):
        batch(observed_at=earlier, valid_until=later, revisions=[row(
            known_at=earlier, collected_at=later)])


def test_direct_event_gate_uses_elapsed_utc_time_across_dst_fold():
    from alladin.challenge.event_policy import CalendarSnapshot, EconomicEvent

    zone = ZoneInfo("America/New_York")
    release = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=0)
    later = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=1)
    c = CalendarSnapshot(release, later, "fixture", (
        EconomicEvent("CPI", release, frozenset({"EURUSD"}), True),))
    d = EventPolicy().evaluate(symbol="EURUSD", now=later, snapshot=c, restrict_news=True)
    assert d.verdict == EventVerdict.ALLOW  # one real hour after release


def test_dst_spring_gap_is_not_silently_normalized():
    nonexistent = datetime(2026, 3, 8, 2, 30, tzinfo=ZoneInfo("America/New_York"))
    with pytest.raises(ValidationError, match="DST"):
        CalendarRevision.model_validate(row(release_at=nonexistent))


@pytest.mark.parametrize("value", [True, "3.4"])
def test_macro_numbers_are_not_coerced(value):
    with pytest.raises(ValidationError):
        CalendarRevision.model_validate(row(forecast=value))


def test_simultaneous_events_have_complete_order_independent_audit_ids():
    from alladin.challenge.event_policy import CalendarSnapshot, EconomicEvent

    events = tuple(EconomicEvent(name, NOW, frozenset({"EURUSD"}), True) for name in ("B", "A"))
    one = CalendarSnapshot(NOW, NOW, "fixture", events)
    two = CalendarSnapshot(NOW, NOW, "fixture", tuple(reversed(events)))
    for restriction in (False, True):
        a = EventPolicy().evaluate(symbol="EURUSD", now=NOW, snapshot=one, restrict_news=restriction)
        b = EventPolicy().evaluate(symbol="EURUSD", now=NOW, snapshot=two, restrict_news=restriction)
        assert a == b and a.event_ids == ("A", "B")


@pytest.mark.parametrize("symbol,rule", [("", True), (" EURUSD", True), ("EURUSD", "false"), ("EURUSD", 0)])
def test_direct_event_gate_rejects_ambiguous_inputs(symbol, rule):
    result = EventPolicy().evaluate(symbol=symbol, now=NOW, snapshot=batch().snapshot(), restrict_news=rule)
    assert result.verdict == EventVerdict.BLOCK
