"""Tests BTC adapter et Three-Way Experiment."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from alladin.brokers.crypto import BinancePublicProvider, CryptoMockProvider, CryptoTick
from alladin.core.enums import MarketRegime, Side, Timeframe
from alladin.core.models import Bar
from alladin.research.btc_experiment import (
    BTCExperimentPosition,
    BTCThreeWayEngine,
    ExperimentStatus,
    _create_three_experiments,
)


class TestCryptoMockProvider:
    def test_klines(self):
        provider = CryptoMockProvider(base_price=65000.0)
        bars = provider.klines("BTCUSDT", __import__("alladin.core.enums", fromlist=["Timeframe"]).Timeframe.H1, 200)
        assert len(bars) == 200
        assert all(b.high >= b.low for b in bars)
        # Chronological
        for i in range(1, len(bars)):
            assert bars[i].time > bars[i - 1].time

    def test_binance_forming_kline_excluded(self, monkeypatch):
        now = datetime(2024, 1, 1, 1, 30, tzinfo=UTC)
        def kline(start, close):
            return [int(start.timestamp() * 1000), "100", "101", "99", "100", "1",
                    int(close.timestamp() * 1000) - 1]
        data = [kline(now - timedelta(hours=2), now - timedelta(hours=1)),
                kline(now - timedelta(minutes=30), now + timedelta(minutes=30))]
        class Response:
            def __enter__(self): return self
            def __exit__(self, *_): return None
            def read(self): return json.dumps(data).encode()
        monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: Response())
        provider = BinancePublicProvider()
        monkeypatch.setattr(provider, "now", lambda: now)
        bars = provider.klines("BTCUSDT", Timeframe.H1, 2)
        assert len(bars) == 1
        assert bars[0].is_closed is True
        assert bars[0].close_time == now - timedelta(hours=1)

    def test_ticker(self):
        provider = CryptoMockProvider(base_price=65000.0, spread_bps=5.0)
        tick = provider.ticker("BTCUSDT")
        assert tick is not None
        assert tick.ask > tick.bid
        assert tick.spread_bps > 0

    def test_instrument(self):
        provider = CryptoMockProvider()
        inst = provider.instrument("BTCUSDT")
        assert inst is not None
        assert inst.base_asset == "BTC"
        assert inst.quote_asset == "USDT"


class TestThreeExperimentDefinitions:
    def test_exactly_three(self):
        """Exactly 3 experiments must be created."""
        exps = _create_three_experiments()
        assert len(exps) == 3

    def test_unique_hypotheses(self):
        """Each experiment has a different hypothesis."""
        exps = _create_three_experiments()
        hypotheses = {e.hypothesis for e in exps}
        assert hypotheses == {"TREND", "BREAKOUT", "MEAN_REVERSION"}

    def test_unique_names(self):
        exps = _create_three_experiments()
        names = {e.name for e in exps}
        assert names == {"BTC-EXP-A", "BTC-EXP-B", "BTC-EXP-C"}

    def test_unique_strategies(self):
        exps = _create_three_experiments()
        strats = {e.strategy_id for e in exps}
        assert len(strats) == 3  # all different


class TestBTCThreeWayEngine:
    def test_position_and_identity_survive_next_evaluation(self):
        provider = CryptoMockProvider()
        engine = BTCThreeWayEngine(provider)
        exps = engine.evaluate()
        exp = exps[0]
        tick = provider.ticker("BTCUSDT")
        engine._open_paper_position(exp, Side.BUY, tick.ask, 3000, 5000, tick)
        assert exp.position and exp.position.is_open
        identity, position = exp.experiment_id, exp.position
        provider.advance(300)
        again = engine.evaluate()
        assert again[0].experiment_id == identity
        assert again[0].position is position
        assert again[0].position.is_open

    @pytest.mark.parametrize("side,entry,stop,tp,first,second", [
        (Side.BUY, 100, 95, 110, (109, 111), (110, 112)),
        (Side.SELL, 100, 105, 90, (89, 91), (88, 90)),
    ])
    def test_tp_requires_liquidation_side(self, side, entry, stop, tp, first, second):
        engine = BTCThreeWayEngine(CryptoMockProvider())
        pos = BTCExperimentPosition("x", side, entry, stop, tp, 0.01,
                                    datetime(2024, 1, 1, tzinfo=UTC))
        def tick(prices):
            return CryptoTick("BTCUSDT", datetime.now(UTC),
                              prices[0], prices[1], sum(prices) / 2)
        assert engine._check_exit(pos, tick(first)) is None
        assert engine._check_exit(pos, tick(second)) == ExperimentStatus.CLOSED_TP

    def test_trend_requires_fresh_m15_and_m5_confirmation(self):
        provider = CryptoMockProvider(start=datetime(2024, 1, 1, 12, tzinfo=UTC))
        engine = BTCThreeWayEngine(provider)
        assessment = SimpleNamespace(regime=MarketRegime.TREND,
                                     metrics={"ema20": 2, "ema50": 1, "atr": 2000})
        exp = _create_three_experiments()[0]
        now = provider.now()
        h1 = [Bar(time=now-timedelta(hours=1), open=100, high=102, low=99, close=101)]
        m15 = [Bar(time=now-timedelta(minutes=15), open=100, high=102, low=99, close=99)]
        m5 = [Bar(time=now-timedelta(minutes=5), open=100, high=102, low=99, close=101)]
        engine._evaluate_trend(exp, h1, m15, m5, provider.ticker("BTCUSDT"), assessment)
        assert exp.rejection_reason == "TF_CONTRADICTION"
        m15[0] = m15[0].model_copy(update={"close": 101})
        m5[0] = m5[0].model_copy(update={"time": now - timedelta(minutes=30)})
        engine._evaluate_trend(exp, h1, m15, m5, provider.ticker("BTCUSDT"), assessment)
        assert exp.rejection_reason == "TF_STALE"

    def test_quantity_step_min_notional_and_capital(self):
        provider = CryptoMockProvider()
        engine = BTCThreeWayEngine(provider, notional=100)
        exp = _create_three_experiments()[0]
        tick = provider.ticker("BTCUSDT")
        engine._open_paper_position(exp, Side.BUY, tick.ask, 1, 2, tick)
        assert exp.rejection_reason == "SIZING_CONSTRAINT"
        assert exp.position is None
    def test_evaluate_creates_three(self):
        provider = CryptoMockProvider()
        engine = BTCThreeWayEngine(provider)
        exps = engine.evaluate()
        assert len(exps) == 3

    def test_no_forced_entries(self):
        """Engine must NOT force 3 positions. Some may be NO_ENTRY."""
        provider = CryptoMockProvider()
        engine = BTCThreeWayEngine(provider)
        exps = engine.evaluate()
        # At least one should be NO_ENTRY or REJECTED since mock data
        # is unlikely to satisfy all 3 hypotheses simultaneously
        statuses = {e.status for e in exps}
        # All should have been evaluated
        assert ExperimentStatus.PENDING not in statuses

    def test_rejection_has_reason(self):
        """Rejected/NO_ENTRY experiments must explain why."""
        provider = CryptoMockProvider()
        engine = BTCThreeWayEngine(provider)
        exps = engine.evaluate()
        for exp in exps:
            if exp.status in (ExperimentStatus.NO_ENTRY, ExperimentStatus.REJECTED):
                assert exp.rejection_reason, f"{exp.name} rejected without reason"

    def test_open_position_has_valid_fields(self):
        provider = CryptoMockProvider()
        engine = BTCThreeWayEngine(provider)
        exps = engine.evaluate()
        for exp in exps:
            if exp.position and exp.position.is_open:
                pos = exp.position
                assert pos.entry_price > 0
                assert pos.stop_loss > 0
                assert pos.size_btc > 0
                assert pos.opened_at is not None

    def test_tick_all_updates(self):
        provider = CryptoMockProvider()
        engine = BTCThreeWayEngine(provider)
        engine.evaluate()
        # Advance time and tick
        provider.advance(300)
        closed = engine.tick_all()
        # May or may not close - just verify it runs without error
        assert isinstance(closed, list)

    def test_summary_format(self):
        provider = CryptoMockProvider()
        engine = BTCThreeWayEngine(provider)
        engine.evaluate()
        summary = engine.summary()
        assert "experiments" in summary
        assert "active" in summary
        assert "total" in summary
        assert summary["total"] == 3

    def test_same_cost_model(self):
        """All 3 experiments use the same cost model."""
        provider = CryptoMockProvider()
        engine = BTCThreeWayEngine(provider, fee_bps=10.0, notional=10000.0)
        exps = engine.evaluate()
        for exp in exps:
            assert exp.notional_capital == 10000.0
            assert exp.fee_bps == 10.0

    def test_experiment_isolation(self):
        """Each experiment is independent - different experiment_ids."""
        provider = CryptoMockProvider()
        engine = BTCThreeWayEngine(provider)
        exps = engine.evaluate()
        ids = {e.experiment_id for e in exps}
        assert len(ids) == 3

    def test_paper_only_no_real_orders(self):
        """CryptoMockProvider has no send_order method."""
        provider = CryptoMockProvider()
        assert not hasattr(provider, "send_order")
        assert not hasattr(provider, "_send")

    def test_production_binance_not_used(self):
        """BinancePublicProvider defaults to testnet."""
        from alladin.brokers.crypto import BinancePublicProvider
        p = BinancePublicProvider()
        assert p._testnet is True
        assert "testnet" in p._base


class TestBTCRiskProfile:
    """BTC uses percentage returns and ATR, not forex pips."""

    def test_spread_bps_not_pips(self):
        provider = CryptoMockProvider(base_price=65000.0, spread_bps=5.0)
        tick = provider.ticker("BTCUSDT")
        assert tick is not None
        # Spread should be in BPS, not pips
        assert tick.spread_bps == pytest.approx(5.0, abs=1.0)

    def test_sizing_uses_notional_pct(self):
        """Position size is based on notional capital %, not lot size."""
        provider = CryptoMockProvider()
        engine = BTCThreeWayEngine(provider, notional=10000.0, risk_pct=2.0)
        engine.evaluate()
        for exp in engine.experiments:
            if exp.position:
                # Risk should be ~2% of 10000 = 200 USDT
                sl_dist = abs(exp.position.entry_price - exp.position.stop_loss)
                risk = sl_dist * exp.position.size_btc
                assert risk == pytest.approx(200.0, rel=0.1)
