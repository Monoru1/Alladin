"""Cycle autonome : NO TRADE, agent, validation d'intent, dry-run vs exécution, kill switch, reprise."""

from __future__ import annotations

from datetime import timedelta

import pytest

from alladin.agents.base import AgentDecision, AgentIntentDraft
from alladin.agents.mock import MockAgent
from alladin.brokers.mock import MockBroker
from alladin.core.enums import DecisionKind, MarketRegime, RunState, Side
from alladin.journal.models import EventType
from alladin.orchestration.bootstrap import Components
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
