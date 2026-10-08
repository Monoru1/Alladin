"""Synthetic contracts and deterministic account protection; no official rules inferred."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from alladin.challenge.account_policy import (
    AccountConstraints,
    AccountPolicyState,
    DrawdownRule,
    ExposurePosition,
    ExposureSnapshot,
    MarketBreak,
    MarketSchedule,
)
from alladin.challenge.event_policy import CalendarSnapshot, EconomicEvent
from alladin.challenge.policy_gate import GateVerdict, ProposedAction, evaluate_action
from alladin.core.enums import Side
from alladin.market.sessions import SessionRules
from tests.test_policy_gate_validation import context

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)


def ctx(**rules):
    c = context()
    profile = replace(c.firm_profile, constraints=AccountConstraints(account_ref="a", currency="USD", **rules))
    return replace(c, firm_profile=profile)


def state(**changes):
    values = dict(account_ref="a", currency="USD", observed_at=NOW, valid_until=NOW+timedelta(days=1),
                  initial_balance=100000., balance=100000., equity=100000.,
                  peak_balance=100000., peak_equity=100000., peak_eod_balance=100000.)
    values.update(changes)
    return AccountPolicyState(**values)


def schedule(**changes):
    values = dict(observed_at=NOW, valid_until=NOW+timedelta(days=4), source="synthetic broker",
                  covered_symbols=frozenset({"EURUSD"}), breaks=(MarketBreak(symbol="EURUSD",
                  starts_at=NOW+timedelta(minutes=4), ends_at=NOW+timedelta(days=3), weekend=True),))
    values.update(changes)
    return MarketSchedule(**values)


@pytest.mark.parametrize("action", list(ProposedAction))
def test_weekend_preclose_reviews_hold_and_permits_compliant_exit(action):
    c = replace(ctx(forbid_weekend_hold=True), market_schedule=schedule())
    d = evaluate_action(action, c)
    expected = GateVerdict.ALLOW if action == ProposedAction.CLOSE else (
        GateVerdict.BLOCK if action == ProposedAction.OPEN else GateVerdict.REVIEW)
    assert d.verdict == expected
    assert d.reason == ("POLICY_CLEAR" if action == ProposedAction.CLOSE else "FLATTEN_BEFORE_MARKET_BREAK")


@pytest.mark.parametrize("action", list(ProposedAction))
@pytest.mark.parametrize("schedule_value", [None, "stale", "uncovered"])
def test_holding_rules_require_fresh_symbol_schedule(action, schedule_value):
    supplied = None if schedule_value is None else schedule(
        valid_until=NOW-timedelta(seconds=1), observed_at=NOW-timedelta(days=1)) if schedule_value == "stale" else schedule(covered_symbols=frozenset({"XAUUSD"}), breaks=())
    d = evaluate_action(action, replace(ctx(forbid_weekend_hold=True), market_schedule=supplied))
    assert d.verdict == (GateVerdict.BLOCK if action == ProposedAction.OPEN else GateVerdict.REVIEW)


@pytest.mark.parametrize("seconds,expected", [(7200, GateVerdict.ALLOW), (7201, GateVerdict.BLOCK)])
def test_overnight_rule_uses_injected_break_duration(seconds, expected):
    b = MarketBreak(symbol="EURUSD", starts_at=NOW+timedelta(minutes=1),
                    ends_at=NOW+timedelta(minutes=1, seconds=seconds), weekend=False)
    d = evaluate_action(ProposedAction.OPEN, replace(ctx(max_market_break_seconds=7200), market_schedule=schedule(breaks=(b,))))
    assert d.verdict == expected


@pytest.mark.parametrize("mode,peak_balance,peak_equity,eod,expected_floor", [
    ("static", 110000., 120000., 110000., 90000.),
    ("trailing_balance", 110000., 120000., 110000., 100000.),
    ("trailing_equity", 110000., 120000., 110000., 110000.),
    ("trailing_eod", 110000., 120000., 100000., 90000.),
])
def test_trailing_modes_and_exact_limit(mode, peak_balance, peak_equity, eod, expected_floor):
    rule = DrawdownRule(mode=mode, loss_pct=10.)
    s = state(balance=100000., equity=expected_floor, peak_balance=peak_balance, peak_equity=peak_equity, peak_eod_balance=eod)
    assert s.floor(rule) == expected_floor
    c = replace(ctx(drawdown=rule), account_state=s)
    assert evaluate_action(ProposedAction.OPEN, c).reason == "DRAWDOWN_LIMIT"
    assert evaluate_action(ProposedAction.CLOSE, c).verdict == GateVerdict.ALLOW
    assert evaluate_action(ProposedAction.HOLD, c).verdict == GateVerdict.REVIEW


def test_eod_highwater_changes_only_on_explicit_settlement_and_restores():
    s = state().advance(balance=110000., equity=120000., observed_at=NOW+timedelta(seconds=1), valid_until=NOW+timedelta(hours=1))
    assert s.peak_eod_balance == 100000.
    recovered = AccountPolicyState.model_validate_json(s.model_dump_json())
    next_state = recovered.advance(balance=108000., equity=108000., observed_at=NOW+timedelta(seconds=2), valid_until=NOW+timedelta(hours=1), end_of_day=True)
    assert next_state.peak_balance == 110000. and next_state.peak_eod_balance == 108000.
    assert next_state.floor(DrawdownRule(mode="trailing_equity", loss_pct=10., lock_floor_at_initial=True)) == 100000.
    with pytest.raises(ValueError, match="causally"):
        next_state.advance(balance=100000., equity=100000., observed_at=NOW, valid_until=NOW)


@pytest.mark.parametrize("bad", [dict(account_ref="b"), dict(currency="EUR"), dict(valid_until=NOW-timedelta(seconds=1), observed_at=NOW-timedelta(days=1))])
def test_account_incoherence_blocks_entry_and_reviews_protection(bad):
    c = replace(ctx(drawdown=DrawdownRule(mode="static", loss_pct=10.)), account_state=state(**bad))
    assert evaluate_action(ProposedAction.OPEN, c).verdict == GateVerdict.BLOCK
    assert evaluate_action(ProposedAction.CLOSE, c).verdict == GateVerdict.REVIEW


def exposure(**changes):
    values = dict(observed_at=NOW, valid_until=NOW+timedelta(hours=1), currency="USD",
                  account_refs=frozenset({"a", "b"}), positions=(ExposurePosition(position_id="p1", account_ref="b",
                  symbol="EURUSD", side=Side.SELL, risk_amount=100., group="USD"),))
    values.update(changes)
    return ExposureSnapshot(**values)


@pytest.mark.parametrize("rules,risk,reason", [
    ({"max_aggregate_positions": 1}, 0., "AGGREGATE_POSITION_LIMIT"),
    ({"max_aggregate_risk": 150.}, 51., "AGGREGATE_RISK_LIMIT"),
    ({"max_group_risk": 150.}, 51., "GROUP_RISK_LIMIT"),
    ({"forbid_opposite_accounts": True}, 0., "OPPOSITE_ACCOUNT_EXPOSURE"),
])
def test_aggregate_limits_across_accounts(rules, risk, reason):
    c = replace(ctx(managed_accounts=frozenset({"a", "b"}), **rules), exposures=exposure(),
                proposed_risk_amount=risk, exposure_group="USD", proposed_side=Side.BUY)
    assert evaluate_action(ProposedAction.OPEN, c).reason == reason
    assert evaluate_action(ProposedAction.CLOSE, c).verdict == GateVerdict.ALLOW


def test_exact_risk_capacity_allowed_but_missing_scope_or_conversion_is_not():
    c = replace(ctx(managed_accounts=frozenset({"a", "b"}), max_aggregate_risk=150.), exposures=exposure(),
                proposed_risk_amount=50., exposure_group="USD")
    assert evaluate_action(ProposedAction.OPEN, c).verdict == GateVerdict.ALLOW
    assert evaluate_action(ProposedAction.OPEN, replace(c, exposures=exposure(currency="EUR"))).reason == "EXPOSURE_CURRENCY_MISMATCH"
    assert evaluate_action(ProposedAction.OPEN, replace(c, exposures=exposure(account_refs=frozenset({"a"}), positions=()))).reason == "EXPOSURE_UNAVAILABLE"
    assert evaluate_action(ProposedAction.OPEN, replace(c, proposed_risk_amount=float("nan"))).reason == "PROPOSED_EXPOSURE_UNAVAILABLE"


@pytest.mark.parametrize("action", [ProposedAction.CLOSE, ProposedAction.PARTIAL_CLOSE, ProposedAction.MODIFY_STOP, ProposedAction.HOLD])
def test_protection_does_not_override_contractual_news_conflict(action):
    c = context()
    calendar = CalendarSnapshot(NOW, NOW+timedelta(minutes=1), "synthetic", (EconomicEvent("CPI", NOW, frozenset({"EURUSD"}), True),))
    c = replace(c, calendar=calendar, restrict_news=True, protective=True, native_protection_active=True)
    d = evaluate_action(action, c)
    assert d.verdict == GateVerdict.REVIEW and d.reason == "PROTECTIVE_NEWS_CONFLICT"
    assert d.event_ids == ("CPI",)


def test_caution_does_not_delay_compliant_protective_exit():
    c = context()
    calendar = CalendarSnapshot(NOW, NOW+timedelta(minutes=1), "synthetic", (EconomicEvent("CPI", NOW, frozenset({"EURUSD"}), True),))
    assert evaluate_action(ProposedAction.CLOSE, replace(c, calendar=calendar, protective=True)).verdict == GateVerdict.ALLOW
    assert evaluate_action(ProposedAction.CLOSE, replace(c, calendar=calendar)).verdict == GateVerdict.DEFER


def test_sessions_and_action_restrictions_are_configured():
    c = ctx(sessions=SessionRules(weekdays=frozenset({0})))
    assert evaluate_action(ProposedAction.OPEN, c).reason == "TRADING_SESSION_CLOSED"
    assert evaluate_action(ProposedAction.CLOSE, c).verdict == GateVerdict.ALLOW
    c = ctx(permitted_actions=frozenset({"HOLD"}))
    assert evaluate_action(ProposedAction.CLOSE, c).reason == "ACTION_NOT_PERMITTED"


@pytest.mark.parametrize("changes", [dict(max_aggregate_risk=float("inf")), dict(permitted_actions=frozenset({"SEND"})),
                                      dict(max_aggregate_positions=1), dict(max_market_break_seconds=True)])
def test_invalid_constraints_rejected(changes):
    with pytest.raises(ValidationError):
        AccountConstraints(account_ref="a", currency="USD", **changes)
