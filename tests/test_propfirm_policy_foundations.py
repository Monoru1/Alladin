"""DECISION 032-034: pure deterministic policy contracts, no live orders."""
from datetime import UTC, datetime, timedelta

import pytest

from alladin.challenge.capital_metrics import CapitalLedger
from alladin.challenge.event_policy import (
    CalendarSnapshot,
    EconomicEvent,
    EventPolicy,
    EventVerdict,
)
from alladin.challenge.firm_policy import (
    FirmProfile,
    FirmVerdict,
    check_new_entry,
)

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)


def calendar(*, release_offset=0, valid_seconds=600, restricted=True):
    return CalendarSnapshot(
        as_of=NOW - timedelta(minutes=1),
        valid_until=NOW + timedelta(seconds=valid_seconds),
        source="test fixture",
        events=(EconomicEvent(
            "US-CPI", NOW + timedelta(minutes=release_offset),
            frozenset({"US100.cash", "XAUUSD", "EURUSD"}), restricted=restricted,
        ),),
    )


def test_calendar_missing_and_stale_fail_closed():
    policy = EventPolicy()
    assert policy.evaluate(symbol="XAUUSD", now=NOW, snapshot=None, restrict_news=False).verdict == EventVerdict.BLOCK
    assert policy.evaluate(symbol="XAUUSD", now=NOW + timedelta(hours=1), snapshot=calendar(), restrict_news=False).verdict == EventVerdict.BLOCK


def test_ftmo_news_restriction_blocks_targeted_instrument():
    decision = EventPolicy().evaluate(symbol="US100.cash", now=NOW, snapshot=calendar(), restrict_news=True)
    assert (decision.verdict, decision.reason, decision.event_ids) == (EventVerdict.BLOCK, "FIRM_RESTRICTED_EVENT", ("US-CPI",))


def test_evaluation_is_not_automatically_firm_restricted_but_is_cautious():
    d = EventPolicy().evaluate(symbol="XAUUSD", now=NOW, snapshot=calendar(), restrict_news=False)
    assert d.verdict == EventVerdict.DEFER


def test_unaffected_symbol_clear_and_preannouncement_defer():
    p = EventPolicy()
    assert p.evaluate(symbol="EURGBP", now=NOW, snapshot=calendar(), restrict_news=True).verdict == EventVerdict.ALLOW
    c = calendar(release_offset=10)
    assert p.evaluate(symbol="EURUSD", now=NOW, snapshot=c, restrict_news=True).verdict == EventVerdict.DEFER


def test_future_revision_not_visible_in_replay():
    event = EconomicEvent("late", NOW, frozenset({"EURUSD"}), True, NOW + timedelta(minutes=5))
    c = CalendarSnapshot(NOW - timedelta(minutes=1), NOW + timedelta(minutes=1), "fixture", (event,))
    assert EventPolicy().evaluate(symbol="EURUSD", now=NOW, snapshot=c, restrict_news=True).verdict == EventVerdict.ALLOW


def profile(**changes):
    data = dict(firm="fixture", program="two-step", phase="funded", account_type="standard",
                version="2026-10", source_url="https://example.test/rules",
                verified_at=NOW - timedelta(days=1), valid_until=NOW + timedelta(days=1),
                allowed_symbols=frozenset({"EURUSD"}), ea_allowed=True, max_open_positions=2)
    data.update(changes)
    return FirmProfile(**data)


def test_missing_expired_or_forbidden_profile_blocks():
    assert check_new_entry(None, now=NOW, symbol="EURUSD", open_positions=0).verdict == FirmVerdict.BLOCK
    assert check_new_entry(profile(ea_allowed=False), now=NOW, symbol="EURUSD", open_positions=0).reason == "AUTOMATION_NOT_PERMITTED"
    assert check_new_entry(profile(), now=NOW + timedelta(days=4), symbol="EURUSD", open_positions=0).reason == "FIRM_PROFILE_STALE"
    assert check_new_entry(profile(), now=NOW, symbol="XAUUSD", open_positions=0).reason == "SYMBOL_NOT_AUTHORIZED"
    assert check_new_entry(profile(), now=NOW, symbol="EURUSD", open_positions=2).reason == "POSITION_LIMIT"
    assert check_new_entry(profile(), now=NOW, symbol="EURUSD", open_positions=1).verdict == FirmVerdict.ALLOW


def test_capital_ledger_does_not_count_simulated_allocation_as_cash():
    ledger = CapitalLedger(200000, 500, 2400, 100, 300)
    assert ledger.net_cash_generated == 1500
    assert ledger.payout_to_fee_ratio == pytest.approx(4.8)
    assert CapitalLedger(100000, 0, 0, 0, 0).payout_to_fee_ratio is None
    with pytest.raises(ValueError):
        CapitalLedger(100000, -1, 0, 0, 0)
