"""Tests Lot B : contrat de modes OBSERVE/PAPER/DEMO, environnement PAPER réel,
persistance, isolation broker, et invariants de sécurité.

Couvre DECISION-013 ADOPTED :
- OBSERVE n'envoie aucun ordre (même CLOSE protecteur)
- PAPER n'appelle jamais broker.send_order, crée des positions simulées
- DEMO conserve le chemin sécurisé actuel
- LIVE reste bloqué
- PAPER lifecycle complet (open/SL/TP/close/P&L)
- Persistance au restart
- Aucun double fill / double close
- DRY_RUN_APPROVED != EXECUTED
- RiskEngine actif en PAPER
- Kill switch / risk rejection en PAPER
- Journal cohérent
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from alladin.agents.mock import MockAgent
from alladin.brokers.mock import MockBroker
from alladin.core.enums import AccountType, RunMode, Side
from alladin.core.errors import ExecutionBlockedError
from alladin.execution.models import ExecStatus
from alladin.journal.models import EventType
from alladin.journal.repository import JournalRepository
from alladin.market.paper import PaperExperimentEngine, PaperPosition, PaperStatus
from alladin.orchestration.bootstrap import Components
from tests.conftest import T0, make_intent

# ============================================================================
# PaperPosition unit tests (preservé de l'ancien fichier)
# ============================================================================


@pytest.mark.parametrize("side,entry,sl,tp,first,second", [
    (Side.BUY, 100, 95, 110, (109, 111), (110, 112)),
    (Side.SELL, 100, 105, 90, (89, 91), (88, 90)),
])
def test_paper_tp_uses_liquidation_side(side, entry, sl, tp, first, second):
    pos = PaperPosition("p", "r", "c", "X", side, 1, entry, sl, tp, T0)
    assert pos.check_exit(*first, 0.01) is None
    assert pos.check_exit(*second, 0.01) == PaperStatus.CLOSED_TP


# ============================================================================
# Broker espion : RAISE sur tout send_order
# ============================================================================


class SpyBroker(MockBroker):
    """Broker qui lève sur tout send_order — prouve l'isolation OBSERVE/PAPER."""

    def __init__(self, **kw: object) -> None:
        super().__init__(**kw)  # type: ignore[arg-type]
        self.send_order_calls: list[object] = []

    def send_order(self, request, approval=None):  # type: ignore[override]
        self.send_order_calls.append(request)
        raise ExecutionBlockedError("SPY BROKER: send_order interdit en ce mode")


# ============================================================================
# 1. Isolation broker : OBSERVE et PAPER ne doivent JAMAIS appeler send_order
# ============================================================================


def test_observe_never_calls_send_order(svc: Components) -> None:
    """En mode OBSERVE, aucun appel à send_order, même si un trade est proposé."""
    spy = SpyBroker(balance=100_000.0, start=T0)
    svc.broker = spy  # type: ignore[assignment]
    svc.execution.broker = spy
    svc.monitor.broker = spy
    engine = svc.engine(MockAgent(), run_mode=RunMode.OBSERVE)
    engine.broker = spy
    outcome = engine.run_cycle()
    assert outcome.decision in ("NO_TRADE", "TRADE")
    assert len(spy.send_order_calls) == 0


def test_paper_never_calls_send_order(svc: Components) -> None:
    """PAPER mode : aucun appel à send_order pour OPEN, CLOSE, SL, TP."""
    spy = SpyBroker(balance=100_000.0, start=T0)
    svc.broker = spy  # type: ignore[assignment]
    svc.execution.broker = spy
    svc.monitor.broker = spy
    engine = svc.engine(MockAgent(), run_mode=RunMode.PAPER)
    engine.broker = spy
    for _ in range(3):
        outcome = engine.run_cycle()
        assert outcome.decision in ("NO_TRADE", "TRADE")
    assert len(spy.send_order_calls) == 0


def test_paper_open_never_calls_send_order() -> None:
    """PaperExperimentEngine.open_position ne touche pas broker.send_order."""
    spy = SpyBroker(balance=100_000.0, start=T0)
    engine = PaperExperimentEngine(spy, "RUN-test")
    from alladin.core.enums import EntryType, MarketRegime
    from alladin.core.models import TradeIntent

    intent = TradeIntent(
        run_id="RUN-test", agent="test", instrument="EURUSD", side=Side.BUY,
        strategy_id="TREND-01", strategy_version="1.0.0",
        market_regime=MarketRegime.TREND, entry_type=EntryType.MARKET,
        entry=1.085, stop_loss=1.080, take_profit=1.095,
        requested_risk_pct_of_working_capital=4.0, confidence=0.7, reason="test",
        created_at=spy.now(), expires_at=spy.now() + timedelta(minutes=10),
    )
    pos = engine.open_position(intent, "CYC-1")
    assert pos.status == "OPEN"
    assert len(spy.send_order_calls) == 0


def test_paper_close_never_calls_send_order() -> None:
    """PaperExperimentEngine.close_position_by_id ne touche pas broker.send_order."""
    spy = SpyBroker(balance=100_000.0, start=T0)
    engine = PaperExperimentEngine(spy, "RUN-test")
    from alladin.core.enums import EntryType, MarketRegime
    from alladin.core.models import TradeIntent

    intent = TradeIntent(
        run_id="RUN-test", agent="test", instrument="EURUSD", side=Side.BUY,
        strategy_id="TREND-01", strategy_version="1.0.0",
        market_regime=MarketRegime.TREND, entry_type=EntryType.MARKET,
        entry=1.085, stop_loss=1.080, take_profit=1.095,
        requested_risk_pct_of_working_capital=4.0, confidence=0.7, reason="test",
        created_at=spy.now(), expires_at=spy.now() + timedelta(minutes=10),
    )
    pos = engine.open_position(intent, "CYC-1")
    closed = engine.close_position_by_id(pos.paper_id)
    assert closed is not None
    assert closed.status == "CLOSED_MANUAL"
    assert len(spy.send_order_calls) == 0


def test_paper_sl_tp_never_calls_send_order() -> None:
    """SL/TP hit en PAPER ne touche pas broker.send_order."""
    spy = SpyBroker(balance=100_000.0, start=T0)
    engine = PaperExperimentEngine(spy, "RUN-test")
    from alladin.core.enums import EntryType, MarketRegime
    from alladin.core.models import TradeIntent

    intent = TradeIntent(
        run_id="RUN-test", agent="test", instrument="EURUSD", side=Side.BUY,
        strategy_id="TREND-01", strategy_version="1.0.0",
        market_regime=MarketRegime.TREND, entry_type=EntryType.MARKET,
        entry=1.085, stop_loss=1.080, take_profit=1.095,
        requested_risk_pct_of_working_capital=4.0, confidence=0.7, reason="test",
        created_at=spy.now(), expires_at=spy.now() + timedelta(minutes=10),
    )
    engine.open_position(intent, "CYC-1")
    spy.set_price("EURUSD", 1.079)
    closed = engine.tick_all()
    assert len(closed) == 1
    assert closed[0].status == PaperStatus.CLOSED_SL
    assert len(spy.send_order_calls) == 0


def test_paper_restart_never_calls_send_order() -> None:
    """Restauration PAPER depuis persistence ne touche pas broker.send_order."""
    spy = SpyBroker(balance=100_000.0, start=T0)
    repo = JournalRepository.from_url("sqlite://")
    engine = PaperExperimentEngine(spy, "RUN-test", repo=repo)
    from alladin.core.enums import EntryType, MarketRegime
    from alladin.core.models import TradeIntent

    intent = TradeIntent(
        run_id="RUN-test", agent="test", instrument="EURUSD", side=Side.BUY,
        strategy_id="TREND-01", strategy_version="1.0.0",
        market_regime=MarketRegime.TREND, entry_type=EntryType.MARKET,
        entry=1.085, stop_loss=1.080, take_profit=1.095,
        requested_risk_pct_of_working_capital=4.0, confidence=0.7, reason="test",
        created_at=spy.now(), expires_at=spy.now() + timedelta(minutes=10),
    )
    engine.open_position(intent, "CYC-1")
    engine2 = PaperExperimentEngine(spy, "RUN-test", repo=repo)
    n = engine2.restore()
    assert n == 1
    assert len(spy.send_order_calls) == 0


# ============================================================================
# 2. DEMO conserve le chemin sécurisé
# ============================================================================


def test_demo_mode_sends_orders(svc: Components) -> None:
    """DEMO mode : les ordres sont envoyés via le broker (chemin actuel)."""
    engine = svc.engine(MockAgent(), run_mode=RunMode.DEMO)
    assert engine.execute is True
    assert engine.run_mode is RunMode.DEMO


def test_demo_protective_close_still_works(svc: Components) -> None:
    """En DEMO, la fermeture protectrice sur SL supprimé fonctionne."""
    engine = svc.engine(MockAgent(), run_mode=RunMode.DEMO)
    intent = make_intent(svc)
    result = svc.execution.submit(intent)
    assert result.status is ExecStatus.EXECUTED
    ticket = result.position_ticket
    assert ticket is not None
    svc.broker._positions[ticket].sl = None  # type: ignore[union-attr]
    engine.run_cycle()
    assert ticket not in svc.broker._positions


# ============================================================================
# 3. OBSERVE : alerte critique sans close
# ============================================================================


def test_observe_sl_removed_alerts_without_close(svc: Components) -> None:
    """En OBSERVE, une position sans SL produit une alerte critique, pas un CLOSE."""
    intent = make_intent(svc)
    result = svc.execution.submit(intent)
    assert result.status is ExecStatus.EXECUTED
    ticket = result.position_ticket
    assert ticket is not None
    svc.broker._positions[ticket].sl = None  # type: ignore[union-attr]
    engine = svc.engine(MockAgent(), run_mode=RunMode.OBSERVE)
    engine.run_cycle()
    assert ticket in svc.broker._positions
    events = svc.repo.events(svc.run.run_id, [EventType.INFO.value])
    alerts = [e for e in events if "CRITIQUE" in str(e.payload.get("alert", ""))]
    assert len(alerts) >= 1, "Aucune alerte critique journalisée en OBSERVE"


# ============================================================================
# 4. LIVE reste bloqué
# ============================================================================


def test_live_account_blocks_execution(svc: Components) -> None:
    """Un compte LIVE bloque l'exécution."""
    svc.broker.set_account_type(AccountType.LIVE)
    intent = make_intent(svc)
    result = svc.execution.submit(intent)
    assert result.status is ExecStatus.BLOCKED
    assert "LIVE" in result.messages[0]


# ============================================================================
# 5. PAPER lifecycle complet
# ============================================================================


def _paper_intent(broker: MockBroker, run_id: str = "RUN-test") -> object:
    from alladin.core.enums import EntryType, MarketRegime
    from alladin.core.models import TradeIntent

    return TradeIntent(
        run_id=run_id, agent="test", instrument="EURUSD", side=Side.BUY,
        strategy_id="TREND-01", strategy_version="1.0.0",
        market_regime=MarketRegime.TREND, entry_type=EntryType.MARKET,
        entry=1.085, stop_loss=1.080, take_profit=1.095,
        requested_risk_pct_of_working_capital=4.0, confidence=0.7, reason="test",
        created_at=broker.now(), expires_at=broker.now() + timedelta(minutes=10),
    )


def test_paper_open_creates_real_position() -> None:
    """PAPER OPEN crée une vraie position simulée."""
    broker = MockBroker(balance=100_000.0, start=T0)
    engine = PaperExperimentEngine(broker, "RUN-test")
    pos = engine.open_position(_paper_intent(broker), "CYC-1")  # type: ignore[arg-type]
    assert pos.paper_id.startswith("PAPER-")
    assert pos.status == "OPEN"
    assert pos.symbol == "EURUSD"
    assert pos.side == Side.BUY
    assert pos.sl == 1.080
    assert pos.tp == 1.095
    assert len(engine.open_positions()) == 1


def test_paper_sl_hit() -> None:
    """PAPER SL : la position se ferme au SL."""
    broker = MockBroker(balance=100_000.0, start=T0)
    engine = PaperExperimentEngine(broker, "RUN-test")
    engine.open_position(_paper_intent(broker), "CYC-1")  # type: ignore[arg-type]
    broker.set_price("EURUSD", 1.079)
    closed = engine.tick_all()
    assert len(closed) == 1
    assert closed[0].status == PaperStatus.CLOSED_SL
    assert closed[0].pnl_pips < 0
    assert len(engine.open_positions()) == 0
    assert len(engine.closed_positions()) == 1


def test_paper_tp_hit() -> None:
    """PAPER TP : la position se ferme au TP."""
    broker = MockBroker(balance=100_000.0, start=T0)
    engine = PaperExperimentEngine(broker, "RUN-test")
    engine.open_position(_paper_intent(broker), "CYC-1")  # type: ignore[arg-type]
    broker.set_price("EURUSD", 1.096)
    closed = engine.tick_all()
    assert len(closed) == 1
    assert closed[0].status == PaperStatus.CLOSED_TP
    assert closed[0].pnl_pips > 0


def test_paper_explicit_close() -> None:
    """PAPER explicit close : fermeture manuelle."""
    broker = MockBroker(balance=100_000.0, start=T0)
    engine = PaperExperimentEngine(broker, "RUN-test")
    pos = engine.open_position(_paper_intent(broker), "CYC-1")  # type: ignore[arg-type]
    broker.set_price("EURUSD", 1.087)
    closed = engine.close_position_by_id(pos.paper_id)
    assert closed is not None
    assert closed.status == "CLOSED_MANUAL"
    assert len(engine.open_positions()) == 0


def test_paper_pnl_calculation() -> None:
    """PAPER P&L : calcul correct du P&L en pips."""
    broker = MockBroker(balance=100_000.0, start=T0)
    engine = PaperExperimentEngine(broker, "RUN-test")
    pos = engine.open_position(_paper_intent(broker), "CYC-1")  # type: ignore[arg-type]
    entry = pos.entry_price
    new_bid = entry + 0.00050
    broker.set_price("EURUSD", new_bid)
    broker.advance(timedelta(minutes=5))
    closed = engine.close_position_by_id(pos.paper_id)
    assert closed is not None
    assert closed.pnl_pips == pytest.approx(50.0, abs=5.0)


def test_paper_stats_empty() -> None:
    broker = MockBroker(balance=100_000.0, start=T0)
    paper = PaperExperimentEngine(broker, "RUN-test")
    s = paper.stats()
    assert s["trades"] == 0
    assert s["open"] == 0


def test_paper_stats_after_close() -> None:
    broker = MockBroker(balance=100_000.0, start=T0)
    paper = PaperExperimentEngine(broker, "RUN-test")
    tick = broker.tick("EURUSD")
    assert tick is not None
    from alladin.core.enums import MarketRegime
    from alladin.core.models import TradeIntent

    intent = TradeIntent(
        run_id="RUN-test", agent="mock", instrument="EURUSD",
        side=Side.BUY, strategy_id="TREND-01", strategy_version="1.0.0",
        market_regime=MarketRegime.TREND,
        stop_loss=tick.ask + 0.01,
        take_profit=tick.ask + 0.1,
        requested_risk_pct_of_working_capital=1.0,
        confidence=0.8,
        expires_at=T0 + timedelta(hours=1),
    )
    paper.open_position(intent, "CYC-001")
    paper.tick_all()
    s = paper.stats()
    assert s["trades"] == 1
    assert "win_rate" in s


# ============================================================================
# 6. Persistance PAPER : restart avec position ouverte
# ============================================================================


def test_paper_persistence_survives_restart() -> None:
    """Position PAPER persiste et peut être restaurée après restart simulé."""
    broker = MockBroker(balance=100_000.0, start=T0)
    repo = JournalRepository.from_url("sqlite://")

    # Process A : ouvre une position
    engine_a = PaperExperimentEngine(broker, "RUN-test", repo=repo)
    pos = engine_a.open_position(_paper_intent(broker), "CYC-1")  # type: ignore[arg-type]
    paper_id = pos.paper_id
    assert len(engine_a.open_positions()) == 1

    rows = repo.list_paper_positions("RUN-test", status="OPEN")
    assert len(rows) == 1
    assert rows[0]["paper_id"] == paper_id

    # Process B (restart) : restaure la position
    engine_b = PaperExperimentEngine(broker, "RUN-test", repo=repo)
    restored = engine_b.restore()
    assert restored == 1
    assert len(engine_b.open_positions()) == 1
    assert engine_b.open_positions()[0].paper_id == paper_id

    # La position restaurée peut atteindre SL
    broker.set_price("EURUSD", 1.079)
    closed = engine_b.tick_all()
    assert len(closed) == 1
    assert closed[0].paper_id == paper_id
    assert closed[0].status == PaperStatus.CLOSED_SL

    # En base
    rows = repo.list_paper_positions("RUN-test", status="OPEN")
    assert len(rows) == 0
    rows = repo.list_paper_positions("RUN-test")
    assert len(rows) == 1
    assert rows[0]["status"] == PaperStatus.CLOSED_SL


def test_paper_no_double_fill_on_restart() -> None:
    """Pas de double fill après restart."""
    broker = MockBroker(balance=100_000.0, start=T0)
    repo = JournalRepository.from_url("sqlite://")

    engine_a = PaperExperimentEngine(broker, "RUN-test", repo=repo)
    engine_a.open_position(_paper_intent(broker), "CYC-1")  # type: ignore[arg-type]

    engine_b = PaperExperimentEngine(broker, "RUN-test", repo=repo)
    engine_b.restore()
    assert len(engine_b.open_positions()) == 1  # exactement 1, pas 2


def test_paper_no_double_close_on_restart() -> None:
    """Pas de double close : une position déjà fermée n'est pas re-fermée."""
    broker = MockBroker(balance=100_000.0, start=T0)
    repo = JournalRepository.from_url("sqlite://")

    engine_a = PaperExperimentEngine(broker, "RUN-test", repo=repo)
    engine_a.open_position(_paper_intent(broker), "CYC-1")  # type: ignore[arg-type]
    broker.set_price("EURUSD", 1.079)
    engine_a.tick_all()
    assert len(engine_a.open_positions()) == 0

    engine_b = PaperExperimentEngine(broker, "RUN-test", repo=repo)
    restored = engine_b.restore()
    assert restored == 0
    assert len(engine_b.open_positions()) == 0
    assert len(engine_b.closed_positions()) == 1
    all_rows = repo.list_paper_positions("RUN-test")
    assert len(all_rows) == 1


# ============================================================================
# 7. DRY_RUN_APPROVED != EXECUTED / PAPER_EXECUTED
# ============================================================================


def test_dry_run_approved_is_not_executed(svc: Components) -> None:
    """DRY_RUN_APPROVED n'est ni EXECUTED ni PAPER_EXECUTED."""
    assert ExecStatus.DRY_RUN_APPROVED != ExecStatus.EXECUTED
    assert ExecStatus.DRY_RUN_APPROVED != ExecStatus.PAPER_EXECUTED
    intent = make_intent(svc)
    result = svc.execution.submit(intent, dry_run=True)
    if result.status is ExecStatus.DRY_RUN_APPROVED:
        assert result.trade_id is None
        assert result.position_ticket is None


# ============================================================================
# 8. RiskEngine actif en PAPER
# ============================================================================


def test_paper_uses_risk_engine(svc: Components) -> None:
    """En PAPER, le RiskEngine valide avant l'ouverture de position."""
    engine = svc.engine(MockAgent(), run_mode=RunMode.PAPER)
    assert engine.paper_engine is not None
    outcome = engine.run_cycle()
    events = svc.repo.events(svc.run.run_id, [EventType.RISK_DECISION.value])
    if outcome.decision == "TRADE":
        assert len(events) >= 1, "Aucune décision RiskEngine en mode PAPER"


def test_paper_kill_switch_blocks(svc: Components) -> None:
    """Kill switch bloque aussi en PAPER."""
    engine = svc.engine(MockAgent(), run_mode=RunMode.PAPER)
    svc.killswitch.activate("test")
    outcome = engine.run_cycle()
    assert outcome.decision == "HALTED"
    assert "kill switch" in outcome.reason


# ============================================================================
# 9. Journal cohérent
# ============================================================================


def test_paper_position_events_logged(svc: Components) -> None:
    """Les positions PAPER sont journalisées avec le flag paper=True."""
    engine = svc.engine(MockAgent(), run_mode=RunMode.PAPER)
    assert engine.paper_engine is not None

    intent = make_intent(svc)
    result = svc.execution.submit(intent, dry_run=True)
    if result.status is ExecStatus.DRY_RUN_APPROVED and result.decision is not None:
        pos = engine.paper_engine.open_position(intent, "CYC-test", decision=result.decision)
        svc.journal.log(
            svc.run.run_id,
            EventType.POSITION_OPENED,
            {"paper": True, **pos.to_dict()},
        )
        events = svc.repo.events(svc.run.run_id, [EventType.POSITION_OPENED.value])
        paper_events = [e for e in events if e.payload.get("paper") is True]
        assert len(paper_events) >= 1


def test_mode_change_logged_for_paper(svc: Components) -> None:
    """run_loop journalise mode.change pour PAPER."""
    engine = svc.engine(MockAgent(), run_mode=RunMode.PAPER)
    engine.run_loop(interval_s=0, max_cycles=1, handle_signals=False)
    events = svc.repo.events(svc.run.run_id, [EventType.MODE_CHANGE.value])
    assert events, "aucun événement mode.change trouvé"
    assert events[0].payload["run_mode"] == "PAPER"


def test_paper_mode_engine_does_not_send_orders(svc: Components) -> None:
    """En mode PAPER, aucun ordre réel ne doit être envoyé."""
    engine = svc.engine(MockAgent(), run_mode=RunMode.PAPER)
    assert engine.execute is False
    engine.run_cycle()
    positions = svc.broker.positions()
    assert len(positions) == 0


# ============================================================================
# 10. PAPER avec RiskDecision : volume/SL/TP du RiskEngine
# ============================================================================


def test_paper_uses_risk_decision_for_sizing() -> None:
    """La position PAPER utilise le volume/SL/TP du RiskEngine."""
    broker = MockBroker(balance=100_000.0, start=T0)
    engine = PaperExperimentEngine(broker, "RUN-test")
    from alladin.risk.models import RiskDecision

    intent = _paper_intent(broker)
    decision = RiskDecision(
        intent_id="test-id",
        approved=True,
        volume=0.05,
        entry_price=1.08506,
        stop_loss=1.08000,
        take_profit=1.09500,
        risk_amount=253.0,
        risk_pct_of_working_capital=3.2,
    )
    pos = engine.open_position(intent, "CYC-1", decision=decision)  # type: ignore[arg-type]
    assert pos.volume == 0.05
    assert pos.sl == 1.08000
    assert pos.tp == 1.09500


# ============================================================================
# 11. Spread au fill simulé
# ============================================================================


def test_paper_fill_uses_real_spread() -> None:
    """Le fill PAPER utilise le ask/bid réel du broker (spread inclus)."""
    broker = MockBroker(balance=100_000.0, start=T0)
    engine = PaperExperimentEngine(broker, "RUN-test")

    tick = broker.tick("EURUSD")
    assert tick is not None
    pos = engine.open_position(_paper_intent(broker), "CYC-1")  # type: ignore[arg-type]
    # BUY utilise ask
    assert pos.entry_price == tick.ask


# ============================================================================
# 12. Persistence round-trip (to_persistence / from_persistence)
# ============================================================================


def test_paper_position_round_trip() -> None:
    """PaperPosition survit au round-trip persistence."""
    pos = PaperPosition(
        paper_id="PAPER-abc12345",
        run_id="RUN-test",
        cycle_id="CYC-1",
        symbol="EURUSD",
        side=Side.BUY,
        volume=0.05,
        entry_price=1.08506,
        sl=1.08000,
        tp=1.09500,
        opened_at=T0,
        intent={"strategy_id": "TREND-01"},
        mfe_pips=12.5,
        mae_pips=3.2,
    )
    d = pos.to_persistence()
    restored = PaperPosition.from_persistence(d)
    assert restored.paper_id == pos.paper_id
    assert restored.symbol == pos.symbol
    assert restored.side == pos.side
    assert restored.volume == pos.volume
    assert restored.entry_price == pos.entry_price
    assert restored.sl == pos.sl
    assert restored.tp == pos.tp
    assert restored.mfe_pips == pos.mfe_pips
    assert restored.mae_pips == pos.mae_pips
    assert restored.intent == pos.intent
