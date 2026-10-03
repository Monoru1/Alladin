"""Cycle autonome : NO TRADE, agent, validation d'intent, dry-run vs exécution, kill switch, reprise."""

from __future__ import annotations

from datetime import timedelta

import pytest

from alladin.agents.base import AgentDecision, AgentIntentDraft
from alladin.agents.mock import MockAgent
from alladin.brain import Action, ActionProposal, BrainContext, ProposalParameters, proposal_identity
from alladin.brokers.mock import MockBroker
from alladin.core.enums import DecisionKind, MarketRegime, RunMode, RunState, Side
from alladin.journal.models import EventType
from alladin.orchestration.bootstrap import Components
from alladin.replay import ReplayContext
from alladin.research.models import StrategyStatus, StrategyVersion
from alladin.research.repository import ResearchRepository


@pytest.fixture(autouse=True)
def approved_test_strategies(svc: Components) -> None:
    """Ces tests d'execution portent sur des versions explicitement approuvees."""
    repo = ResearchRepository.from_engine(svc.repo.engine)
    for strategy_id in ("TREND-01", "BREAKOUT-01", "RANGE-01"):
        repo.save_version(StrategyVersion(
            strategy_id=strategy_id, version="1.0.0", code_hash="test-hash",
            created_at=svc.broker.now(),
        ))
        for status in (
            StrategyStatus.FORMALIZED, StrategyStatus.BACKTESTING,
            StrategyStatus.BACKTEST_PASSED, StrategyStatus.OOS_TESTING,
            StrategyStatus.OOS_PASSED, StrategyStatus.DEMO_TESTING,
            StrategyStatus.CANDIDATE, StrategyStatus.APPROVED,
        ):
            repo.update_status(strategy_id, "1.0.0", status)


def draft_for(svc: Components, symbol: str, **over: object) -> AgentIntentDraft:
    b = svc.broker
    tick, spec = b.tick(symbol), b.symbol_spec(symbol)
    assert tick and spec
    pip = spec.point * 10
    data: dict[str, object] = dict(
        instrument=symbol, side=Side.BUY, strategy_id="TREND-01", strategy_version="1.0.0", market_regime=MarketRegime.TREND,
        entry=tick.ask, stop_loss=round(tick.ask - 20 * pip, spec.digits), take_profit=round(tick.ask + 50 * pip, spec.digits),
        requested_risk_pct_of_working_capital=3, confidence=0.7, reason="test",
    )  # fmt: skip
    data.update(over)
    return AgentIntentDraft(**data)  # type: ignore[arg-type]


def shortlist(svc: Components) -> list[str]:
    return [c.symbol for c in svc.engine(MockAgent(), execute=False).scanner.scan().candidates]


def test_no_trade_cycle_is_journaled_with_everything_needed_for_later_analysis(svc: Components) -> None:
    agent = MockAgent(
        [AgentDecision(decision=DecisionKind.NO_TRADE, reason="rien d'intéressant aujourd'hui")]
    )
    out = svc.engine(agent, execute=True).run_cycle()
    assert out.decision == "NO_TRADE" and "rien d'intéressant" in out.reason
    (ev,) = svc.repo.events(svc.run.run_id, [EventType.NO_TRADE])
    p = ev.payload
    assert p["final_decision"] == "NO_TRADE" and p["agent_consulted"] == "mock"
    assert (
        p["candidates"]
        and p["instruments_studied"]
        and "USDTRY" in p["rejections"]
        and p["strategies_evaluated"]
    )
    types = {e.type for e in svc.repo.events(svc.run.run_id)}
    assert {
        EventType.SCAN.value,
        EventType.AGENT_REQUEST.value,
        EventType.AGENT_RESPONSE.value,
        EventType.ROUTING.value,
    } <= types
    assert svc.broker.positions() == []  # type: ignore[attr-defined]


def test_agent_request_carries_no_secrets_and_no_volume_field(svc: Components) -> None:
    agent = MockAgent([AgentDecision(decision=DecisionKind.NO_TRADE)])
    svc.engine(agent, execute=False).run_cycle()
    ctx = agent.calls[0].context
    blob = str(ctx).lower()
    assert "password" not in blob and "login" not in blob and "mt5_" not in blob
    assert ctx["account"]["max_trade_risk"] > 0 and ctx["rules"]["stop_loss_required"] is True
    assert all("volume" not in s["draft"] for s in ctx["signals"])


def test_trade_proposed_by_agent_goes_through_risk_engine_and_executes(svc: Components) -> None:
    sym = shortlist(svc)[0]
    agent = MockAgent([AgentDecision(decision=DecisionKind.TRADE, reason="ok", intent=draft_for(svc, sym))])
    out = svc.engine(agent, execute=True).run_cycle()
    assert out.decision == "TRADE" and "EXECUTED" in out.reason
    (t,) = svc.repo.trades_for_run(svc.run.run_id, "OPEN")
    assert (
        t.symbol == sym
        and t.strategy_id == "TREND-01"
        and t.strategy_version == "1.0.0"
        and t.agent == "mock"
    )
    assert t.risk_pct_of_wc <= 3.0 + 0.1


def test_dry_run_evaluates_but_never_sends(svc: Components) -> None:
    sym = shortlist(svc)[0]
    agent = MockAgent([AgentDecision(decision=DecisionKind.TRADE, intent=draft_for(svc, sym))])
    out = svc.engine(agent, execute=False).run_cycle()
    assert "DRY_RUN_APPROVED" in out.reason
    assert svc.broker.sent_orders == [] and svc.repo.trades_for_run(svc.run.run_id) == []  # type: ignore[attr-defined]


def test_agent_cannot_trade_outside_the_scanned_shortlist_or_with_an_unknown_strategy(
    svc: Components,
) -> None:
    sym = shortlist(svc)[0]
    outside = next(s.symbol for s in svc.broker.list_symbols() if s.symbol not in shortlist(svc))
    bad_inst = draft_for(svc, outside)  # dans l'univers mais hors shortlist
    bad_strat = draft_for(svc, sym, strategy_id="GOD-MODE")
    bad_ver = draft_for(svc, sym, strategy_version="0.0.1")
    for d in (bad_inst, bad_strat, bad_ver):
        agent = MockAgent([AgentDecision(decision=DecisionKind.TRADE, intent=d)])
        out = svc.engine(agent, execute=True).run_cycle()
        assert out.decision == "NO_TRADE" and "intent refusé" in out.reason
    assert svc.repo.events(svc.run.run_id, [EventType.INTENT_REJECTED_SCHEMA])
    assert svc.repo.trades_for_run(svc.run.run_id) == []


def test_agent_numbers_are_not_trusted_the_risk_engine_rejects_them(svc: Components) -> None:
    sym = shortlist(svc)[0]
    crazy = draft_for(svc, sym, stop_loss=None)  # pas de SL
    out = svc.engine(
        MockAgent([AgentDecision(decision=DecisionKind.TRADE, intent=crazy)]), execute=True
    ).run_cycle()
    assert out.decision == "NO_TRADE" and "NO SL" in out.reason
    greedy = draft_for(svc, sym, requested_risk_pct_of_working_capital=50)
    out = svc.engine(
        MockAgent([AgentDecision(decision=DecisionKind.TRADE, intent=greedy)]), execute=True
    ).run_cycle()
    assert out.decision == "NO_TRADE" and "plafond" in out.reason
    assert svc.repo.trades_for_run(svc.run.run_id) == []


def test_unusable_agent_answer_becomes_no_trade(svc: Components) -> None:
    class Broken(MockAgent):
        def propose(self, request):  # type: ignore[no-untyped-def]
            from alladin.agents.base import AgentResponse

            return AgentResponse(agent="broken", errors=["timeout"])

    out = svc.engine(Broken(), execute=True).run_cycle()
    assert out.decision == "NO_TRADE" and "inexploitable" in out.reason


def test_kill_switch_halts_the_loop_and_kills_the_run(svc: Components) -> None:
    eng = svc.engine(MockAgent(), execute=True)
    svc.manager.kill(svc.run, "test kill")
    assert svc.killswitch.is_active() and svc.run.watchdog.run_state is RunState.KILLED
    out = eng.run_cycle()
    assert out.decision == "HALTED"
    assert svc.repo.events(svc.run.run_id, [EventType.KILL_SWITCH])
    assert svc.repo.get_run(svc.run.run_id).state == "KILLED"  # type: ignore[union-attr]


def test_loop_stops_when_run_fails(svc: Components, broker: MockBroker) -> None:
    broker.inject_pnl(-6_000)
    seen = []
    svc.engine(MockAgent(), execute=True).run_loop(
        0, max_cycles=5, on_cycle=seen.append, sleep=lambda _: None
    )
    assert len(seen) == 1 and seen[0].run_state == "FAILED" and seen[0].decision == "HALTED"


def test_positions_are_monitored_each_cycle(svc: Components, broker: MockBroker) -> None:
    sym = shortlist(svc)[0]
    eng = svc.engine(MockAgent([AgentDecision(decision=DecisionKind.TRADE, intent=draft_for(svc, sym)),
                                AgentDecision(decision=DecisionKind.NO_TRADE)]), execute=True)  # fmt: skip
    assert eng.run_cycle().decision == "TRADE"
    (pos,) = broker.positions()
    tick = broker.tick(sym)
    assert tick and pos.tp
    broker.set_price(sym, pos.tp + 0.0001 if pos.tp < 50 else pos.tp + 0.01)  # TP touché entre deux cycles
    broker.advance(timedelta(minutes=5))
    eng.run_cycle()
    (t,) = svc.repo.trades_for_run(svc.run.run_id)
    assert t.status == "CLOSED" and t.close_reason == "TP"


def test_proposal_journal_links_opportunity_risk_trade_and_replay(svc: Components) -> None:
    sym = shortlist(svc)[0]
    agent = MockAgent([AgentDecision(decision=DecisionKind.TRADE, intent=draft_for(svc, sym))])
    out = svc.engine(agent, run_mode=RunMode.DEMO).run_cycle()
    assert out.decision == "TRADE"
    events = svc.repo.events(svc.run.run_id, cycle_id=out.cycle_id)
    proposal = next(e.payload for e in events if e.type == EventType.ACTION_PROPOSAL)
    opp = next(e.payload for e in events if e.type == EventType.OPPORTUNITY_CREATED
               and e.payload["symbol"] == sym)
    risk = next(e.payload for e in events if e.type == EventType.RISK_DECISION)
    trade = svc.repo.trades_for_run(svc.run.run_id)[0]
    assert proposal["opportunity_id"] == opp["opportunity_id"] == trade.opportunity_id
    assert proposal["proposal_id"] == risk["proposal_id"] == trade.proposal_id == trade.trade_id
    replay = ReplayContext.from_cycle(svc.repo, out.cycle_id)
    assert any(e["type"] == EventType.ACTION_PROPOSAL for e in replay.events)
    assert replay.market_bars.get(sym)


def test_explicit_no_trade_proposal_is_persisted(svc: Components) -> None:
    out = svc.engine(MockAgent([AgentDecision(decision=DecisionKind.NO_TRADE, reason="abstention")])).run_cycle()
    assert out.decision == "NO_TRADE"
    proposal = svc.repo.events(svc.run.run_id, [EventType.ACTION_PROPOSAL])[0].payload
    no = svc.repo.events(svc.run.run_id, [EventType.NO_TRADE])[0].payload
    assert proposal["action"] == "NO_TRADE" and proposal["proposal_id"] == no["proposal_id"]


class StaticBrain:
    source_id = "baseline"
    source_version = "1"

    def __init__(self, action: Action = Action.LONG, *, bad: bool = False, raises: bool = False,
                 entry: ProposalParameters | None = None, wrong_time: bool = False) -> None:
        self.action, self.bad, self.raises, self.entry, self.wrong_time = action, bad, raises, entry, wrong_time

    def decide(self, context: BrainContext) -> ActionProposal:
        if self.raises:
            raise RuntimeError("brain offline")
        symbol, opp = next(iter(context.opportunities.items()))
        if self.action is Action.LONG:
            params = self.entry or ProposalParameters(strategy_id="TREND-01", strategy_version="1.0.0",
                                                      requested_risk_pct_of_working_capital=3)
        else:
            params = ProposalParameters(position_ticket=999)
        return ActionProposal(
            proposal_id=proposal_identity(context.run_id, context.cycle_id, opp,
                                          self.source_id, self.source_version),
            source_id=self.source_id, source_version=self.source_version,
            run_id=context.run_id, cycle_id=context.cycle_id, opportunity_id=opp,
            symbol=None if self.bad else symbol, action=self.action,
            timestamp=context.timestamp + timedelta(days=1) if self.wrong_time else context.timestamp,
            parameters=params,
        )


def test_brain_exception_and_invalid_output_fail_closed(svc: Components) -> None:
    for brain in (StaticBrain(raises=True), StaticBrain(bad=True), StaticBrain(wrong_time=True)):
        out = svc.engine(MockAgent(), brain=brain, run_mode=RunMode.DEMO).run_cycle()
        assert out.decision == "NO_TRADE"
    assert len(svc.repo.events(svc.run.run_id, [EventType.BRAIN_FAILURE])) == 3
    assert svc.broker.sent_orders == []  # type: ignore[attr-defined]


def test_management_proposal_is_recorded_and_never_executes_without_policy(svc: Components) -> None:
    out = svc.engine(MockAgent(), brain=StaticBrain(Action.CLOSE), run_mode=RunMode.DEMO).run_cycle()
    assert out.decision == "NO_TRADE"
    assert svc.repo.events(svc.run.run_id, [EventType.POSITION_ACTION_REJECTED])
    assert svc.broker.sent_orders == []  # type: ignore[attr-defined]


def test_brain_failure_does_not_block_protective_close(svc: Components, broker: MockBroker) -> None:
    sym = shortlist(svc)[0]
    svc.engine(MockAgent([AgentDecision(decision=DecisionKind.TRADE, intent=draft_for(svc, sym))]),
               run_mode=RunMode.DEMO).run_cycle()
    (pos,) = broker.positions()
    broker._positions[pos.ticket].sl = None
    out = svc.engine(MockAgent(), brain=StaticBrain(raises=True), run_mode=RunMode.DEMO).run_cycle()
    assert out.decision == "NO_TRADE"
    assert broker.positions() == []


def test_baseline_brain_uses_same_risk_engine_and_rejection_blocks_order(svc: Components,
                                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    seen = []
    original = svc.risk.evaluate

    def evaluate(intent, context):  # type: ignore[no-untyped-def]
        seen.append(intent)
        return original(intent, context)

    monkeypatch.setattr(svc.risk, "evaluate", evaluate)
    out = svc.engine(MockAgent(), brain=StaticBrain(), run_mode=RunMode.DEMO).run_cycle()
    assert out.decision == "NO_TRADE" and "NO SL" in out.reason
    assert len(seen) == 1 and seen[0].proposal_id
    assert svc.repo.events(svc.run.run_id, [EventType.RISK_DECISION])[0].payload["proposal_id"]
    assert svc.broker.sent_orders == []  # type: ignore[attr-defined]


@pytest.mark.parametrize("mode,expected", [
    (RunMode.OBSERVE, "DRY_RUN_APPROVED"),
    (RunMode.PAPER, "PAPER_EXECUTED"),
    (RunMode.DEMO, "EXECUTED"),
])
def test_baseline_brain_valid_entry_preserves_mode_safety(svc: Components, mode: RunMode,
                                                          expected: str) -> None:
    sym = shortlist(svc)[0]
    draft = draft_for(svc, sym)
    params = ProposalParameters(
        strategy_id=draft.strategy_id, strategy_version=draft.strategy_version,
        market_regime=draft.market_regime, entry_type=draft.entry_type, entry=draft.entry,
        stop_loss=draft.stop_loss, take_profit=draft.take_profit,
        requested_risk_pct_of_working_capital=draft.requested_risk_pct_of_working_capital,
    )
    out = svc.engine(MockAgent(), brain=StaticBrain(entry=params), run_mode=mode).run_cycle()
    assert out.decision == "TRADE" and expected in out.reason
    assert len(svc.broker.sent_orders) == (1 if mode is RunMode.DEMO else 0)  # type: ignore[attr-defined]


class HoldBrain:
    source_id = "hold-baseline"
    source_version = "1"

    def decide(self, context: BrainContext) -> ActionProposal:
        pos = context.market["account"]["open_positions"][0]
        return ActionProposal(
            proposal_id=proposal_identity(context.run_id, context.cycle_id,
                                          pos["opportunity_id"], self.source_id, self.source_version),
            source_id=self.source_id, source_version=self.source_version,
            run_id=context.run_id, cycle_id=context.cycle_id,
            opportunity_id=pos["opportunity_id"], symbol=pos["symbol"], action=Action.HOLD,
            timestamp=context.timestamp, parameters=ProposalParameters(position_ticket=pos["ticket"]),
        )


def test_position_hold_passes_deterministic_risk_without_order(svc: Components) -> None:
    sym = shortlist(svc)[0]
    svc.engine(MockAgent([AgentDecision(decision=DecisionKind.TRADE, intent=draft_for(svc, sym))]),
               run_mode=RunMode.DEMO).run_cycle()
    sent = len(svc.broker.sent_orders)  # type: ignore[attr-defined]
    out = svc.engine(MockAgent(), brain=HoldBrain(), run_mode=RunMode.DEMO).run_cycle()
    assert out.decision == "HOLD" and "HOLD validé" in out.reason
    risk = svc.repo.events(svc.run.run_id, [EventType.RISK_DECISION])[-1].payload
    assert risk["action"] == "HOLD" and risk["status"] == "APPROVED"
    assert svc.repo.events(svc.run.run_id, [EventType.POSITION_ACTION])[-1].payload["action"] == "HOLD"
    assert len(svc.broker.sent_orders) == sent  # type: ignore[attr-defined]
    out = svc.engine(MockAgent(), brain=HoldBrain(), run_mode=RunMode.OBSERVE).run_cycle()
    assert out.decision == "NO_TRADE"
    assert svc.repo.events(svc.run.run_id, [EventType.POSITION_ACTION_REJECTED])
    assert len(svc.broker.sent_orders) == sent  # type: ignore[attr-defined]
