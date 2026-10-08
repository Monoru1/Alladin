"""Tests purs de composition : aucun broker, MT5 ni réseau."""
from datetime import UTC, datetime, timedelta

from alladin.challenge.event_policy import CalendarSnapshot, EconomicEvent
from alladin.challenge.firm_policy import FirmProfile
from alladin.challenge.policy_gate import (
    GateVerdict,
    PolicyContext,
    ProposedAction,
    evaluate_action,
)

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)


def firm():
    return FirmProfile(
        firm="fixture", program="challenge", phase="funded",
        account_type="standard", version="1",
        source_url="https://example.test/contract", verified_at=NOW-timedelta(days=1),
        valid_until=NOW+timedelta(days=1),
        allowed_symbols=frozenset({"XAUUSD"}), ea_allowed=True,
        max_open_positions=3,
    )


def calendar():
    return CalendarSnapshot(
        as_of=NOW-timedelta(minutes=1), valid_until=NOW+timedelta(minutes=1),
        source="fixture",
        events=(EconomicEvent("CPI", NOW, frozenset({"XAUUSD"}), restricted=True),),
    )


def ctx(**updates):
    values = dict(now=NOW, symbol="XAUUSD", open_positions=0,
                  firm_profile=firm(), calendar=calendar(), restrict_news=True)
    values.update(updates)
    return PolicyContext(**values)


def test_hold_never_sends_transaction():
    assert evaluate_action(ProposedAction.HOLD, ctx(calendar=None)).verdict is GateVerdict.ALLOW


def test_news_restricted_entry_and_closure_are_blocked():
    for action in (ProposedAction.OPEN, ProposedAction.CLOSE, ProposedAction.PARTIAL_CLOSE):
        d = evaluate_action(action, ctx())
        assert d.verdict is GateVerdict.BLOCK
        assert d.reason == "FIRM_RESTRICTED_EVENT"


def test_missing_firm_and_calendar_are_not_assumed_safe():
    assert evaluate_action(ProposedAction.OPEN, ctx(firm_profile=None)).verdict is GateVerdict.BLOCK
    assert evaluate_action(ProposedAction.CLOSE, ctx(firm_profile=None)).verdict is GateVerdict.REVIEW
    assert evaluate_action(ProposedAction.OPEN, ctx(calendar=None)).verdict is GateVerdict.BLOCK
    assert evaluate_action(ProposedAction.CLOSE, ctx(calendar=None)).verdict is GateVerdict.REVIEW


def test_unknown_news_rules_are_never_assumed_permissive():
    assert evaluate_action(ProposedAction.OPEN, ctx(restrict_news=None)).verdict is GateVerdict.BLOCK
    assert evaluate_action(ProposedAction.CLOSE, ctx(restrict_news=None)).verdict is GateVerdict.REVIEW


def test_precaution_window_defers_entry_but_reviews_stop_change():
    c = ctx(restrict_news=False)
    assert evaluate_action(ProposedAction.OPEN, c).verdict is GateVerdict.DEFER
    assert evaluate_action(ProposedAction.MODIFY_STOP, c).verdict is GateVerdict.REVIEW


def test_unaffected_symbol_is_not_blocked_by_news():
    c = ctx(symbol="EURUSD", firm_profile=FirmProfile(
        firm="fixture", program="challenge", phase="funded",
        account_type="standard", version="1", source_url="https://example.test/contract",
        verified_at=NOW-timedelta(days=1), valid_until=NOW+timedelta(days=1),
        allowed_symbols=frozenset({"EURUSD"}), ea_allowed=True,
    ))
    assert evaluate_action(ProposedAction.OPEN, c).verdict is GateVerdict.ALLOW


def test_position_limit_is_enforced():
    assert evaluate_action(ProposedAction.OPEN, ctx(open_positions=3)).reason == "POSITION_LIMIT"
