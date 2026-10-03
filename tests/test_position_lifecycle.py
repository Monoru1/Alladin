from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text

from alladin.agents.mock import MockAgent
from alladin.brain import Action, ActionProposal, BrainContext, ProposalParameters, proposal_identity
from alladin.core.enums import RunMode, Side
from alladin.core.models import OrderResult
from alladin.execution.position_actions import PositionActions, actions
from alladin.market.paper import PaperExperimentEngine
from alladin.orchestration.bootstrap import Components
from tests.conftest import make_intent


def opened(svc: Components, mode: RunMode, side: Side = Side.BUY) -> PaperExperimentEngine | None:
    intent = make_intent(svc, side=side, opportunity_id="OPP-entry", proposal_id="AP-entry")
    result = svc.execution.submit(intent, dry_run=mode is RunMode.PAPER)
    assert result.decision and result.decision.approved
    if mode is RunMode.PAPER:
        paper = PaperExperimentEngine(svc.broker, svc.run.run_id, repo=svc.repo)
        paper.open_position(intent, "entry", decision=result.decision)
        return paper
    assert result.executed
    return None


def action(svc: Components, mode: RunMode, kind: Action, paper: PaperExperimentEngine | None,
           cycle: str = "manage", **params: object) -> ActionProposal:
    pos = svc.execution.owned_positions(mode, paper)[0]
    values: dict[str, object] = {"position_id": pos.position_id}
    if kind is Action.MODIFY_STOP:
        values["stop_loss"] = 1.084 if pos.side is Side.BUY else 1.086
    elif kind is Action.MODIFY_TARGET:
        values["take_profit"] = 1.089 if pos.side is Side.BUY else 1.081
    elif kind is Action.PARTIAL_CLOSE:
        values["partial_fraction"] = 0.5
    values.update(params)
    return ActionProposal(proposal_id=proposal_identity(svc.run.run_id, cycle, "OPP-entry", "test", "1"),
                          source_id="test", source_version="1", run_id=svc.run.run_id, cycle_id=cycle,
                          opportunity_id="OPP-entry", symbol=pos.symbol, action=kind, timestamp=svc.broker.now(),
                          parameters=ProposalParameters.model_validate(values))


@pytest.mark.parametrize("mode", [RunMode.DEMO, RunMode.PAPER])
@pytest.mark.parametrize("side", [Side.BUY, Side.SELL])
@pytest.mark.parametrize("kind", [Action.HOLD, Action.CLOSE, Action.MODIFY_STOP, Action.MODIFY_TARGET, Action.PARTIAL_CLOSE])
def test_position_action_confirmed_and_persistently_idempotent(svc: Components, mode: RunMode, side: Side, kind: Action) -> None:
    paper = opened(svc, mode, side)
    before = svc.execution.owned_positions(mode, paper)[0]
    req = action(svc, mode, kind, paper)
    sent = len(svc.broker.sent_orders)
    result = svc.execution.submit_position_action(req, mode, paper)
    assert result.confirmed, result
    after = svc.execution.owned_positions(mode, paper)
    if kind is Action.CLOSE:
        assert not after
    else:
        assert after[0].position_id == before.position_id
        assert after[0].original_volume == before.original_volume
        assert after[0].remaining_volume == pytest.approx(before.remaining_volume / 2 if kind is Action.PARTIAL_CLOSE else before.remaining_volume)
        assert after[0].stop_loss == (1.084 if side is Side.BUY else 1.086) if kind is Action.MODIFY_STOP else after[0].stop_loss == before.stop_loss
    assert len(svc.broker.sent_orders) == sent + (mode is RunMode.DEMO and kind is not Action.HOLD)
    # New coordinator object reads the durable claim; it cannot repeat the action.
    svc.execution.position_actions = PositionActions(svc.execution)
    repeat = svc.execution.submit_position_action(req, mode, paper)
    assert repeat.confirmed and repeat.duplicate
    assert len(svc.broker.sent_orders) == sent + (mode is RunMode.DEMO and kind is not Action.HOLD)


def test_ambiguous_acceptance_never_becomes_success_or_retries(svc: Components) -> None:
    opened(svc, RunMode.DEMO)
    req = action(svc, RunMode.DEMO, Action.PARTIAL_CLOSE, None)
    calls = []
    svc.broker._send = lambda request: (calls.append(request) or OrderResult(accepted=True, retcode=10009))  # type: ignore[method-assign]
    result = svc.execution.submit_position_action(req, RunMode.DEMO)
    assert result.status == "PENDING_CONFIRMATION" and len(calls) == 1
    assert svc.execution.submit_position_action(req, RunMode.DEMO).duplicate and len(calls) == 1
    other = action(svc, RunMode.DEMO, Action.CLOSE, None, cycle="other")
    assert svc.execution.submit_position_action(other, RunMode.DEMO).status == "BLOCKED"
    assert len(calls) == 1


def test_response_lost_after_fill_is_reconciled_without_retry(svc: Components) -> None:
    opened(svc, RunMode.DEMO)
    req = action(svc, RunMode.DEMO, Action.PARTIAL_CLOSE, None)
    real = svc.broker._send

    def lost(request: object) -> OrderResult:
        real(request)  # type: ignore[arg-type]
        raise TimeoutError("reply lost")

    svc.broker._send = lost  # type: ignore[method-assign]
    assert svc.execution.submit_position_action(req, RunMode.DEMO).confirmed
    sent = len(svc.broker.sent_orders)
    assert svc.execution.submit_position_action(req, RunMode.DEMO).duplicate
    assert len(svc.broker.sent_orders) == sent


def test_same_id_different_payload_or_mode_is_blocked(svc: Components) -> None:
    opened(svc, RunMode.DEMO)
    req = action(svc, RunMode.DEMO, Action.MODIFY_STOP, None)
    assert svc.execution.submit_position_action(req, RunMode.DEMO).confirmed
    changed = req.model_copy(update={"parameters": req.parameters.model_copy(update={"stop_loss": 1.0841})})
    assert svc.execution.submit_position_action(changed, RunMode.DEMO).status == "BLOCKED"
    assert svc.execution.submit_position_action(req, RunMode.OBSERVE).status == "BLOCKED"


def test_kill_switch_activated_during_precheck_prevents_send(svc: Components) -> None:
    opened(svc, RunMode.DEMO)
    req = action(svc, RunMode.DEMO, Action.CLOSE, None)
    sent = len(svc.broker.sent_orders)
    real = svc.broker.check_order

    def check(request: object) -> object:
        svc.killswitch.activate("during precheck")
        return real(request)  # type: ignore[arg-type]

    svc.broker.check_order = check  # type: ignore[method-assign]
    assert svc.execution.submit_position_action(req, RunMode.DEMO).status == "BLOCKED"
    assert len(svc.broker.sent_orders) == sent


def test_paper_partial_close_accounting_and_restore(svc: Components) -> None:
    paper = opened(svc, RunMode.PAPER)
    assert paper
    initial = paper.open_positions()[0]
    volume = initial.volume
    req = action(svc, RunMode.PAPER, Action.PARTIAL_CLOSE, paper)
    assert svc.execution.submit_position_action(req, RunMode.PAPER, paper).confirmed
    first = paper.open_positions()[0]
    partial_pnl = first.realized_pnl
    assert first.volume == volume / 2 and first.original_volume == volume
    restored = PaperExperimentEngine(svc.broker, svc.run.run_id, repo=svc.repo)
    restored.restore()
    assert restored.open_positions()[0].realized_pnl == partial_pnl
    close = action(svc, RunMode.PAPER, Action.CLOSE, restored, cycle="close")
    assert svc.execution.submit_position_action(close, RunMode.PAPER, restored).confirmed
    closed = restored.closed_positions()[0]
    assert closed.realized_pnl == pytest.approx(partial_pnl * 2)
    assert closed.original_volume == volume and closed.initial_risk > 0
    restored.restore()
    restored.restore()
    assert len(restored.closed_positions()) == 1
    assert svc.broker.sent_orders == []


def test_paper_transaction_failure_preserves_position_and_pending_claim(svc: Components) -> None:
    paper = opened(svc, RunMode.PAPER)
    assert paper
    before = paper.open_positions()[0].to_persistence()
    with svc.repo.engine.begin() as c:
        c.execute(text("CREATE TRIGGER fail_paper_action BEFORE UPDATE ON position_actions WHEN NEW.status='CONFIRMED' BEGIN SELECT RAISE(ABORT, 'simulated crash'); END"))
    req = action(svc, RunMode.PAPER, Action.PARTIAL_CLOSE, paper)
    result = svc.execution.submit_position_action(req, RunMode.PAPER, paper)
    assert result.status == "PENDING_CONFIRMATION"
    paper.restore()
    assert paper.open_positions()[0].to_persistence() == before
    with svc.repo.engine.connect() as c:
        assert c.execute(actions.select()).mappings().one()["status"] == "PENDING_CONFIRMATION"


class SequenceBrain:
    source_id, source_version = "sequence", "1"

    def __init__(self, kind: Action) -> None:
        self.kind = kind

    def decide(self, ctx: BrainContext) -> ActionProposal:
        pos = ctx.positions[0]
        params = ProposalParameters(position_id=pos.position_id,
                                    stop_loss=1.084 if self.kind is Action.MODIFY_STOP else None)
        return ActionProposal(proposal_id=proposal_identity(ctx.run_id, ctx.cycle_id, pos.opportunity_id,
                              self.source_id, self.source_version), source_id=self.source_id, source_version=self.source_version,
                              run_id=ctx.run_id, cycle_id=ctx.cycle_id, opportunity_id=pos.opportunity_id,
                              symbol=pos.symbol, action=self.kind, timestamp=ctx.timestamp, parameters=params)


@pytest.mark.parametrize("mode", [RunMode.PAPER, RunMode.DEMO])
def test_engine_open_hold_modify_close_end_to_end(svc: Components, mode: RunMode) -> None:
    paper = opened(svc, mode)
    for kind in (Action.HOLD, Action.MODIFY_STOP, Action.CLOSE):
        engine = svc.engine(MockAgent(), brain=SequenceBrain(kind), run_mode=mode)
        if paper:
            engine.paper_engine = paper
        result = engine.run_cycle()
        assert result.decision == kind.value, result
    assert svc.execution.owned_positions(mode, paper) == ()
    if mode is RunMode.DEMO:
        trade = svc.repo.trades_for_run(svc.run.run_id)[0]
        assert trade.status == "CLOSED" and trade.r_multiple is not None


def test_older_close_deals_do_not_confirm_new_close(svc: Components) -> None:
    opened(svc, RunMode.DEMO)
    req = action(svc, RunMode.DEMO, Action.PARTIAL_CLOSE, None)
    assert svc.execution.submit_position_action(req, RunMode.DEMO).confirmed
    req = action(svc, RunMode.DEMO, Action.PARTIAL_CLOSE, None, cycle="second")
    svc.broker._send = lambda request: OrderResult(accepted=True, retcode=10009)  # type: ignore[method-assign]
    assert svc.execution.submit_position_action(req, RunMode.DEMO).status == "PENDING_CONFIRMATION"
    svc.broker.advance(timedelta(seconds=1))
    assert not svc.execution.position_actions.reconcile_pending()[0].confirmed


@pytest.mark.parametrize("retcode", [-1, 0])
def test_unknown_broker_response_is_pending_and_never_resent(svc: Components, retcode: int) -> None:
    opened(svc, RunMode.DEMO)
    req = action(svc, RunMode.DEMO, Action.CLOSE, None)
    calls = []
    svc.broker._send = lambda request: (calls.append(request) or OrderResult(accepted=False, retcode=retcode))  # type: ignore[method-assign]
    assert svc.execution.submit_position_action(req, RunMode.DEMO).status == "PENDING_CONFIRMATION"
    assert svc.execution.submit_position_action(req, RunMode.DEMO).duplicate
    assert len(calls) == 1


def test_restart_reopens_durable_claim_without_resending(settings, broker, tmp_path) -> None:
    from alladin.orchestration.bootstrap import build_services

    url = f"sqlite:///{tmp_path / 'restart.db'}"
    svc = build_services(settings, broker, create_run=True, db_url=url)
    assert svc
    svc.manager.start(svc.run, broker.account_info())
    opened(svc, RunMode.DEMO)
    req = action(svc, RunMode.DEMO, Action.CLOSE, None)
    calls = []
    broker._send = lambda request: (calls.append(request) or OrderResult(accepted=False, retcode=-1))
    assert svc.execution.submit_position_action(req, RunMode.DEMO).status == "PENDING_CONFIRMATION"
    svc.repo.engine.dispose()
    resumed = build_services(settings, broker, run_id=svc.run.run_id, db_url=url)
    assert resumed
    result = resumed.execution.submit_position_action(req, RunMode.DEMO)
    assert result.status == "PENDING_CONFIRMATION" and result.duplicate
    assert len(calls) == 1
