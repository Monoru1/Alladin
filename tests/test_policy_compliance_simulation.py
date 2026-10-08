"""Deterministic synthetic contract matrix, not firm admission or runtime readiness."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from alladin.challenge.event_policy import CalendarSnapshot, EconomicEvent
from alladin.challenge.policy_gate import GateVerdict, PolicyContext, ProposedAction, evaluate_action
from tests.policy_fixtures import load_firm_fixtures

FIRMS = load_firm_fixtures()
RELEASE = datetime(2026, 10, 8, 12, tzinfo=UTC)
# Independent expected window table: exact edges included, one second outside.
WINDOWS = [(-901, "CLEAR"), (-900, "CAUTION"), (-121, "CAUTION"),
           (-120, "RESTRICTED"), (0, "RESTRICTED"), (120, "RESTRICTED"), (121, "CLEAR")]


def context(fixture, seconds=0):
    now = RELEASE + timedelta(seconds=seconds)
    p = FIRMS[fixture]
    calendar = CalendarSnapshot(RELEASE-timedelta(hours=1), RELEASE+timedelta(hours=1), "synthetic",
                                (EconomicEvent("CPI", RELEASE, frozenset({"XAUUSD", "US100.cash"}), True),))
    return PolicyContext(now, "US100.cash", 0, p, calendar, p.restrict_news)


@pytest.mark.parametrize("fixture", FIRMS)
@pytest.mark.parametrize("action", list(ProposedAction))
@pytest.mark.parametrize("seconds,window", WINDOWS)
def test_contract_action_time_matrix(fixture, action, seconds, window):
    expected = GateVerdict.ALLOW
    if action == ProposedAction.HOLD:
        pass
    elif fixture in {"no_automation", "unknown_news"}:
        expected = GateVerdict.BLOCK if action == ProposedAction.OPEN else GateVerdict.REVIEW
    elif fixture == "zero_positions" and action == ProposedAction.OPEN or window == "RESTRICTED" and fixture == "funded_standard":
        expected = GateVerdict.BLOCK
    elif window != "CLEAR":
        expected = GateVerdict.REVIEW if action in {ProposedAction.MODIFY_STOP, ProposedAction.MODIFY_TARGET} else GateVerdict.DEFER
    decision = evaluate_action(action, context(fixture, seconds))
    assert decision.verdict == expected


@pytest.mark.parametrize("action", list(ProposedAction))
@pytest.mark.parametrize("failure", ["calendar_missing", "calendar_stale", "profile_expired", "profile_future"])
def test_outage_and_contract_revalidation_matrix(action, failure):
    c = context("funded_standard")
    if failure == "calendar_missing":
        c = replace(c, calendar=None)
    elif failure == "calendar_stale":
        c = replace(c, calendar=replace(c.calendar, valid_until=RELEASE-timedelta(seconds=1)))
    elif failure == "profile_expired":
        c = replace(c, firm_profile=replace(c.firm_profile, valid_until=RELEASE-timedelta(seconds=1)))
    else:
        c = replace(c, firm_profile=replace(c.firm_profile, verified_at=RELEASE+timedelta(seconds=1)))
    expected = GateVerdict.ALLOW if action == ProposedAction.HOLD else (
        GateVerdict.BLOCK if action == ProposedAction.OPEN else GateVerdict.REVIEW)
    assert evaluate_action(action, c).verdict == expected


@pytest.mark.parametrize("action", [ProposedAction.OPEN, ProposedAction.CLOSE])
@pytest.mark.parametrize("rule", [False, None, "false", 0])
def test_caller_cannot_override_profile_news_rule(action, rule):
    result = evaluate_action(action, replace(context("funded_standard"), restrict_news=rule))
    assert result.verdict == (GateVerdict.BLOCK if action == ProposedAction.OPEN else GateVerdict.REVIEW)
    assert result.reason in {"NEWS_RULE_UNVERIFIED", "NEWS_RULE_PROFILE_MISMATCH"}


def test_accounts_remain_independent_and_replay_is_deterministic():
    restricted = context("funded_standard")
    unrestricted = context("funded_swing")
    first = evaluate_action(ProposedAction.OPEN, restricted)
    assert first.verdict == GateVerdict.BLOCK
    assert evaluate_action(ProposedAction.OPEN, unrestricted).verdict == GateVerdict.DEFER
    assert evaluate_action(ProposedAction.OPEN, restricted) == first
    assert evaluate_action(ProposedAction.CLOSE, replace(restricted, open_positions=999)).reason == "FIRM_RESTRICTED_EVENT"
