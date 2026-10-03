"""Deterministic position plans; no broker mutation and no executable token."""

from __future__ import annotations

from datetime import timedelta

import pytest

from alladin.brain import Action, ActionProposal, ProposalParameters, proposal_identity
from alladin.brokers.base import BrokerCapabilities
from alladin.core.enums import AccountType, RunMode, RunState, Side
from alladin.core.models import OwnedPosition
from alladin.orchestration.bootstrap import Components
from alladin.risk.models import RejectCode
from alladin.risk.position import PositionActionContext
from tests.conftest import T0, make_intent


def context(svc: Components, side: Side = Side.BUY, mode: RunMode = RunMode.DEMO) -> PositionActionContext:
    spec = svc.broker.symbol_spec("EURUSD")
    tick = svc.broker.tick("EURUSD")
    assert spec and tick
    return PositionActionContext(
        run_id=svc.run.run_id, mode=mode, account_type=AccountType.DEMO, run_state=RunState.RUNNING,
        now=T0, observed_at=T0, tick=tick, spec=spec, capabilities=svc.broker.capabilities(),
        position=OwnedPosition(position_id="POS-trade", run_id=svc.run.run_id, trade_id="trade",
                               opportunity_id="OPP-entry", broker_ticket=123 if mode is RunMode.DEMO else None,
                               paper_id="PAPER-1" if mode is RunMode.PAPER else None,
                               symbol="EURUSD", side=side, original_volume=0.1, remaining_volume=0.1,
                               entry_price=1.085, stop_loss=1.083 if side is Side.BUY else 1.087,
                               take_profit=1.09 if side is Side.BUY else 1.08, mode=mode))


def proposal(ctx: PositionActionContext, action: Action, **over: object) -> ActionProposal:
    p: dict[str, object] = {"position_id": ctx.position.position_id}
    if action is Action.MODIFY_STOP:
        p["stop_loss"] = 1.084 if ctx.position.side is Side.BUY else 1.086
    if action is Action.MODIFY_TARGET:
        p["take_profit"] = 1.089 if ctx.position.side is Side.BUY else 1.081
    if action is Action.PARTIAL_CLOSE:
        p["partial_fraction"] = 0.5
    p.update(over)
    return ActionProposal(proposal_id=proposal_identity(ctx.run_id, "cycle", "OPP-entry", "test", "1"),
                          source_id="test", source_version="1", run_id=ctx.run_id, cycle_id="cycle",
                          opportunity_id="OPP-entry", symbol="EURUSD", action=action, timestamp=T0,
                          parameters=ProposalParameters.model_validate(p))


MANAGEMENT = [Action.HOLD, Action.CLOSE, Action.MODIFY_STOP, Action.MODIFY_TARGET, Action.PARTIAL_CLOSE]


@pytest.mark.parametrize("mode", [RunMode.DEMO, RunMode.PAPER])
@pytest.mark.parametrize("side", [Side.BUY, Side.SELL])
@pytest.mark.parametrize("action", MANAGEMENT)
def test_valid_management_is_effect_free_plan(svc: Components, mode: RunMode, side: Side, action: Action) -> None:
    ctx = context(svc, side, mode)
    req = proposal(ctx, action)
    before = ctx.model_dump()
    result = svc.execution.risk.plan_position_action(req, ctx)
    assert result.approved and result.token is None
    assert ctx.model_dump() == before and svc.broker.sent_orders == []
    assert result.volume == (0 if action is Action.HOLD else 0.05 if action is Action.PARTIAL_CLOSE else 0.1)
    assert result.stop_loss == (req.parameters.stop_loss if action is Action.MODIFY_STOP else ctx.position.stop_loss)
    assert result.take_profit == (req.parameters.take_profit if action is Action.MODIFY_TARGET else ctx.position.take_profit)


@pytest.mark.parametrize("action", MANAGEMENT)
@pytest.mark.parametrize("update,code", [
    ({"kill_switch_active": True}, RejectCode.KILL_SWITCH),
    ({"run_state": RunState.FAILED}, RejectCode.KILL_SWITCH),
    ({"account_type": AccountType.LIVE}, RejectCode.MODE_SAFETY),
    ({"account_type": AccountType.UNKNOWN}, RejectCode.MODE_SAFETY),
    ({"mode": RunMode.OBSERVE}, RejectCode.MODE_SAFETY),
    ({"observed_at": T0 - timedelta(seconds=61)}, RejectCode.EXPIRED),
    ({"observed_at": T0 + timedelta(seconds=1)}, RejectCode.EXPIRED),
    ({"now": T0.replace(tzinfo=None)}, RejectCode.EXPIRED),
])
def test_global_management_guards(svc: Components, action: Action, update: dict[str, object], code: RejectCode) -> None:
    ctx = context(svc)
    result = svc.execution.risk.plan_position_action(proposal(ctx, action), ctx.model_copy(update=update))
    assert not result.approved and code in [r.code for r in result.reasons]
    assert result.token is None and result.volume == 0 and svc.broker.sent_orders == []


@pytest.mark.parametrize("update,code", [
    ({"run_id": "RUN-999"}, RejectCode.RUN_MISMATCH),
    ({"position_id": "other"}, RejectCode.POSITION_NOT_OWNED),
    ({"opportunity_id": "other"}, RejectCode.POSITION_NOT_OWNED),
    ({"symbol": "GBPJPY"}, RejectCode.POSITION_NOT_OWNED),
    ({"status": "CLOSED"}, RejectCode.POSITION_NOT_OWNED),
    ({"paper_id": "PAPER-foreign"}, RejectCode.MODE_SAFETY),
    ({"remaining_volume": float("nan")}, RejectCode.BAD_GEOMETRY),
    ({"remaining_volume": 0.2}, RejectCode.BAD_GEOMETRY),
])
def test_canonical_ownership_and_position_validity(svc: Components, update: dict[str, object], code: RejectCode) -> None:
    ctx = context(svc)
    req = proposal(ctx, Action.CLOSE)
    bad = ctx.model_copy(update={"position": ctx.position.model_copy(update=update)})
    result = svc.execution.risk.plan_position_action(req, bad)
    assert not result.approved and code in [r.code for r in result.reasons]


def test_ticket_and_position_id_must_both_match(svc: Components) -> None:
    ctx = context(svc)
    result = svc.execution.risk.plan_position_action(proposal(ctx, Action.CLOSE, position_ticket=124), ctx)
    assert not result.approved and result.reasons[0].code is RejectCode.POSITION_NOT_OWNED


@pytest.mark.parametrize("action,cap", [(Action.CLOSE, "can_close_position"),
                                       (Action.PARTIAL_CLOSE, "can_partial_close"),
                                       (Action.MODIFY_STOP, "can_modify_stop"),
                                       (Action.MODIFY_TARGET, "can_modify_target")])
def test_required_broker_capability(svc: Components, action: Action, cap: str) -> None:
    ctx = context(svc)
    caps = dict(ctx.capabilities.__dict__)
    caps[cap] = False
    result = svc.execution.risk.plan_position_action(proposal(ctx, action),
                                                    ctx.model_copy(update={"capabilities": BrokerCapabilities(**caps)}))
    assert not result.approved and RejectCode.POSITION_ACTION_UNSUPPORTED in [r.code for r in result.reasons]


@pytest.mark.parametrize("side,stop", [(Side.BUY, 1.082), (Side.SELL, 1.088)])
def test_stop_cannot_increase_risk(svc: Components, side: Side, stop: float) -> None:
    ctx = context(svc, side)
    result = svc.execution.risk.plan_position_action(proposal(ctx, Action.MODIFY_STOP, stop_loss=stop), ctx)
    assert not result.approved and RejectCode.RISK_EXCEEDS_CAP in [r.code for r in result.reasons]


@pytest.mark.parametrize("action,params", [
    (Action.MODIFY_STOP, {"stop_loss": 1.09}),
    (Action.MODIFY_TARGET, {"take_profit": 1.08}),
    (Action.MODIFY_STOP, {"stop_loss": 1.084939}),
    (Action.MODIFY_TARGET, {"take_profit": 1.0850001}),
])
def test_protection_geometry_and_tick_grid(svc: Components, action: Action, params: dict[str, float]) -> None:
    ctx = context(svc)
    assert not svc.execution.risk.plan_position_action(proposal(ctx, action, **params), ctx).approved


def test_broker_freeze_zone_and_minimum_stops(svc: Components) -> None:
    ctx = context(svc)
    spec = ctx.spec.model_copy(update={"stops_level": 100, "freeze_level": 100})
    result = svc.execution.risk.plan_position_action(proposal(ctx, Action.MODIFY_STOP), ctx.model_copy(update={"spec": spec}))
    assert not result.approved and RejectCode.STOPS_TOO_CLOSE in [r.code for r in result.reasons]


@pytest.mark.parametrize("fraction", [0.001, 1.0])
def test_partial_close_must_leave_valid_residual(svc: Components, fraction: float) -> None:
    ctx = context(svc)
    assert not svc.execution.risk.plan_position_action(proposal(ctx, Action.PARTIAL_CLOSE, partial_fraction=fraction), ctx).approved


@pytest.mark.parametrize("fraction,expected", [(0.333, 0.03), (0.99, 0.09)])
def test_partial_fraction_rounds_down_without_exceeding_requested_volume(svc: Components, fraction: float, expected: float) -> None:
    ctx = context(svc)
    result = svc.execution.risk.plan_position_action(proposal(ctx, Action.PARTIAL_CLOSE, partial_fraction=fraction), ctx)
    assert result.approved and result.volume == expected


@pytest.mark.parametrize("action", MANAGEMENT)
def test_challenge_block_does_not_prevent_non_increasing_risk_plans(svc: Components, action: Action) -> None:
    ctx = context(svc).model_copy(update={"challenge_blocked": True})
    assert svc.execution.risk.plan_position_action(proposal(ctx, action), ctx).approved


def test_unprotected_position_can_close_but_not_modify_target(svc: Components) -> None:
    ctx = context(svc)
    ctx = ctx.model_copy(update={"position": ctx.position.model_copy(update={"stop_loss": None})})
    assert svc.execution.risk.plan_position_action(proposal(ctx, Action.CLOSE), ctx).approved
    assert not svc.execution.risk.plan_position_action(proposal(ctx, Action.MODIFY_TARGET), ctx).approved


@pytest.mark.parametrize("field", ["bid", "ask"])
@pytest.mark.parametrize("value", [0.0, float("nan"), float("inf")])
def test_invalid_tick_fails_closed(svc: Components, field: str, value: float) -> None:
    ctx = context(svc)
    bad = ctx.model_copy(update={"tick": ctx.tick.model_copy(update={field: value})})
    assert not svc.execution.risk.plan_position_action(proposal(ctx, Action.CLOSE), bad).approved


@pytest.mark.parametrize("action", [Action.CLOSE, Action.PARTIAL_CLOSE, Action.MODIFY_STOP, Action.MODIFY_TARGET])
def test_demo_requires_reconciliation_and_trade_permission(svc: Components, action: Action) -> None:
    ctx = context(svc)
    caps = dict(ctx.capabilities.__dict__)
    caps["reliable_position_reconciliation"] = False
    req = proposal(ctx, action)
    assert not svc.execution.risk.plan_position_action(req, ctx.model_copy(
        update={"capabilities": BrokerCapabilities(**caps)})).approved
    assert not svc.execution.risk.plan_position_action(req, ctx.model_copy(update={"trade_allowed": False})).approved
    paper = context(svc, mode=RunMode.PAPER)
    assert svc.execution.risk.plan_position_action(proposal(paper, action), paper.model_copy(
        update={"trade_allowed": False, "capabilities": BrokerCapabilities(name="data-only")})).approved


@pytest.mark.parametrize("field", ["proposal", "tick"])
@pytest.mark.parametrize("offset", [-61, 1])
def test_all_market_decision_clocks_are_checked(svc: Components, field: str, offset: int) -> None:
    ctx, req = context(svc), proposal(context(svc), Action.CLOSE)
    when = T0 + timedelta(seconds=offset)
    if field == "proposal":
        req = req.model_copy(update={"timestamp": when})
    else:
        ctx = ctx.model_copy(update={"tick": ctx.tick.model_copy(update={"time": when})})
    assert not svc.execution.risk.plan_position_action(req, ctx).approved


def test_altered_schema_fails_closed_instead_of_repairing(svc: Components) -> None:
    ctx = context(svc)
    req = proposal(ctx, Action.MODIFY_STOP).model_copy(update={"parameters": ProposalParameters(position_id="POS-trade")})
    assert not svc.execution.risk.plan_position_action(req, ctx).approved


def test_owned_demo_snapshot_survives_stop_and_volume_changes(svc: Components) -> None:
    result = svc.execution.submit(make_intent(svc))
    assert result.position_ticket
    first = svc.execution.owned_positions(RunMode.DEMO)[0]
    pos = svc.broker._positions[result.position_ticket]
    pos.sl = 1.084
    pos.volume /= 2
    second = svc.execution.owned_positions(RunMode.DEMO)[0]
    assert first.position_id == second.position_id and first.trade_id == second.trade_id
    assert second.original_volume == first.original_volume
    assert second.remaining_volume == first.remaining_volume / 2 and second.stop_loss == 1.084
    assert svc.execution.owned_positions(RunMode.OBSERVE) == (second,)
    assert svc.execution.owned_positions(RunMode.PAPER) == ()


def test_owned_view_excludes_foreign_and_untracked_positions(svc: Components) -> None:
    result = svc.execution.submit(make_intent(svc))
    assert result.position_ticket
    svc.broker._positions[result.position_ticket].magic += 1
    assert svc.execution.owned_positions(RunMode.DEMO) == ()
    svc.broker._positions[result.position_ticket].magic -= 1
    svc.repo.update_trade(result.trade_id, status="UNTRACKED")  # type: ignore[arg-type]
    assert svc.execution.owned_positions(RunMode.DEMO) == ()


def test_paper_owned_view_is_isolated_and_keeps_causal_ids(svc: Components) -> None:
    from alladin.market.paper import PaperExperimentEngine

    intent = make_intent(svc, proposal_id="AP-entry", opportunity_id="OPP-entry")
    decision = svc.execution.submit(intent, dry_run=True).decision
    assert decision and decision.approved
    paper = PaperExperimentEngine(svc.broker, svc.run.run_id, repo=svc.repo)
    pos = paper.open_position(intent, "cycle", decision=decision)
    # Also create an actual mock-broker position; PAPER must not include it.
    assert svc.execution.submit(make_intent(svc)).executed
    view = svc.execution.owned_positions(RunMode.PAPER, paper)
    assert len(view) == 1 and view[0].paper_id == pos.paper_id and view[0].broker_ticket is None
    assert view[0].trade_id == intent.intent_id and view[0].proposal_id == "AP-entry"
    assert view[0].opportunity_id == "OPP-entry" and view[0].mode is RunMode.PAPER
    restored = PaperExperimentEngine(svc.broker, svc.run.run_id, repo=svc.repo)
    restored.restore()
    assert svc.execution.owned_positions(RunMode.PAPER, restored) == view
    foreign = PaperExperimentEngine(svc.broker, "RUN-999", repo=svc.repo)
    assert svc.execution.owned_positions(RunMode.PAPER, foreign) == ()
