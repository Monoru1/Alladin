"""Invalid inputs must never create an execution permission."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from alladin.challenge.capital_metrics import CapitalLedger
from alladin.challenge.event_policy import CalendarSnapshot, EconomicEvent
from alladin.challenge.firm_policy import FirmProfile, check_new_entry
from alladin.challenge.policy_gate import GateVerdict, PolicyContext, ProposedAction, evaluate_action

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)


def context():
    profile = FirmProfile("synthetic", "two-step", "funded", "standard", "1",
                          "https://example.test/contract", NOW, NOW + timedelta(days=1),
                          frozenset({"EURUSD"}), True, 2)
    return PolicyContext(NOW, "EURUSD", 0, profile,
                         CalendarSnapshot(NOW, NOW + timedelta(minutes=1), "fixture", ()), False)


@pytest.mark.parametrize("action", list(ProposedAction))
def test_forbidden_automation_requires_review_for_management(action):
    c = context()
    c = replace(c, firm_profile=replace(c.firm_profile, ea_allowed=False))
    expected = GateVerdict.ALLOW if action == ProposedAction.HOLD else (
        GateVerdict.BLOCK if action == ProposedAction.OPEN else GateVerdict.REVIEW)
    assert evaluate_action(action, c).verdict == expected


@pytest.mark.parametrize("action", ["OPEN", "LIQUIDATE", None])
def test_unknown_or_unparsed_action_is_blocked(action):
    assert evaluate_action(action, context()).reason == "UNKNOWN_ACTION"


@pytest.mark.parametrize("count", [-1, 1.5, True])
def test_invalid_position_counts_fail_closed(count):
    c = replace(context(), open_positions=count)
    assert evaluate_action(ProposedAction.OPEN, c).verdict == GateVerdict.BLOCK
    assert evaluate_action(ProposedAction.CLOSE, c).verdict == GateVerdict.REVIEW
    assert check_new_entry(c.firm_profile, now=NOW, symbol="EURUSD", open_positions=count).reason == "INVALID_POSITION_COUNT"


def test_untrusted_clock_escalates_management():
    c = replace(context(), now=NOW.replace(tzinfo=None))
    assert evaluate_action(ProposedAction.OPEN, c).verdict == GateVerdict.BLOCK
    assert evaluate_action(ProposedAction.CLOSE, c).verdict == GateVerdict.REVIEW


@pytest.mark.parametrize("amount", [float("nan"), float("inf"), -float("inf"), -1])
@pytest.mark.parametrize("index", range(5))
def test_nonfinite_ledger_rejected(amount, index):
    amounts = [0.] * 5
    amounts[index] = amount
    with pytest.raises(ValueError):
        CapitalLedger(*amounts)


@pytest.mark.parametrize("symbols", [frozenset(), frozenset({" "}), frozenset({" EURUSD"})])
def test_ambiguous_event_symbols_rejected(symbols):
    with pytest.raises(ValueError):
        EconomicEvent("CPI", NOW, symbols)


def test_duplicate_event_revisions_require_explicit_selection():
    e = EconomicEvent("CPI", NOW, frozenset({"EURUSD"}))
    with pytest.raises(ValueError, match="one revision"):
        CalendarSnapshot(NOW, NOW, "fixture", (e, e))
