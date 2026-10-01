"""Tests : PaperExperimentEngine - simulation de trades sans ordre reel."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from alladin.brokers.mock import MockBroker
from alladin.core.enums import RunMode, Side
from alladin.market.paper import PaperExperimentEngine, PaperPosition, PaperStatus
from alladin.orchestration.bootstrap import Components

T0 = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)


@pytest.mark.parametrize("side,entry,sl,tp,first,second", [
    (Side.BUY, 100, 95, 110, (109, 111), (110, 112)),
    (Side.SELL, 100, 105, 90, (89, 91), (88, 90)),
])
def test_paper_tp_uses_liquidation_side(side, entry, sl, tp, first, second):
    pos = PaperPosition("p", "r", "c", "X", side, 1, entry, sl, tp, T0)
    assert pos.check_exit(*first, 0.01) is None
    assert pos.check_exit(*second, 0.01) == PaperStatus.CLOSED_TP


@pytest.fixture
def broker() -> MockBroker:
    return MockBroker(balance=100_000.0, start=T0)


@pytest.fixture
def paper(broker: MockBroker) -> PaperExperimentEngine:
    return PaperExperimentEngine(broker=broker, run_id="RUN-PAPER-001")


def _make_intent(run_id: str, *, symbol: str = "EURUSD") -> object:
    from alladin.core.enums import MarketRegime
    from alladin.core.models import TradeIntent

    return TradeIntent(
        run_id=run_id,
        agent="mock",
        instrument=symbol,
        side=Side.BUY,
        strategy_id="TREND-01",
        strategy_version="1.0.0",
        market_regime=MarketRegime.TREND,
        stop_loss=1.0900,
        take_profit=1.1300,
        requested_risk_pct_of_working_capital=1.0,
        confidence=0.8,
        expires_at=T0 + timedelta(hours=1),
    )


def test_paper_open_position(paper: PaperExperimentEngine) -> None:
    intent = _make_intent("RUN-PAPER-001")
    pos = paper.open_position(intent, "CYC-001")
    assert pos.paper_id.startswith("PAPER-")
    assert pos.symbol == "EURUSD"
    assert pos.side == Side.BUY
    assert pos.entry_price > 0
    assert pos.status == "OPEN"
    assert len(paper.open_positions()) == 1
    assert len(paper.closed_positions()) == 0


def test_paper_tick_updates_mfe_mae(paper: PaperExperimentEngine) -> None:
    intent = _make_intent("RUN-PAPER-001")
    pos = paper.open_position(intent, "CYC-001")
    paper.tick_all()
    # After tick, MFE or MAE should reflect current price vs entry
    assert pos.mfe_pips >= 0
    assert pos.mae_pips >= 0


def test_paper_sl_closes_position(broker: MockBroker) -> None:
    """Si le prix descend sous le SL, la position doit etre fermee."""
    from alladin.core.enums import MarketRegime
    from alladin.core.models import TradeIntent

    paper = PaperExperimentEngine(broker=broker, run_id="RUN-001")
    # Open a BUY with SL just above current ask (so it triggers immediately)
    tick = broker.tick("EURUSD")
    assert tick is not None
    high_sl = tick.ask + 0.01  # SL above current price -> immediate SL trigger on next tick
    intent = TradeIntent(
        run_id="RUN-001",
        agent="mock",
        instrument="EURUSD",
        side=Side.BUY,
        strategy_id="TREND-01",
        strategy_version="1.0.0",
        market_regime=MarketRegime.TREND,
        stop_loss=high_sl,
        take_profit=tick.ask + 0.1,
        requested_risk_pct_of_working_capital=1.0,
        confidence=0.8,
        expires_at=T0 + timedelta(hours=1),
    )
    paper.open_position(intent, "CYC-001")
    closed = paper.tick_all()
    assert len(closed) == 1
    assert closed[0].status == PaperStatus.CLOSED_SL
    assert len(paper.open_positions()) == 0


def test_paper_stats_empty(paper: PaperExperimentEngine) -> None:
    s = paper.stats()
    assert s["trades"] == 0
    assert s["open"] == 0


def test_paper_stats_after_close(broker: MockBroker) -> None:
    from alladin.core.enums import MarketRegime
    from alladin.core.models import TradeIntent

    paper = PaperExperimentEngine(broker=broker, run_id="RUN-001")
    tick = broker.tick("EURUSD")
    assert tick is not None
    # Force SL close
    intent = TradeIntent(
        run_id="RUN-001", agent="mock", instrument="EURUSD",
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


def test_paper_mode_engine_does_not_send_orders(svc: Components) -> None:
    """En mode PAPER, aucun ordre reel ne doit etre envoye."""
    from alladin.agents.mock import MockAgent
    engine = svc.engine(MockAgent(), run_mode=RunMode.PAPER)
    assert engine.execute is False
    engine.run_cycle()
    # Aucune position reelle ouverte
    positions = svc.broker.positions()
    assert len(positions) == 0
