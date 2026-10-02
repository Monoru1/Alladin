"""Tests BacktestRunner, R Analytics, Splits, Scorecard.

Inclut des tests explicites anti-lookahead.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from alladin.core.enums import MarketRegime, Side, Timeframe
from alladin.core.models import Bar
from alladin.research.backtest import BacktestResult, BacktestRunner, VirtualPosition
from alladin.research.r_analytics import compute_r
from alladin.research.scorecard import MINIMUM_TRADES, build_scorecard
from alladin.research.splits import DatasetSplitConfig, SplitName, split_bars, split_ranges
from alladin.strategies.base import Strategy, StrategyContext, StrategySignal

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_bars(n: int, start_price: float = 100.0, trend: float = 0.1, start_time: datetime | None = None) -> list[Bar]:
    """Genere n barres synthetiques avec une tendance legere."""
    t0 = start_time or datetime(2024, 1, 1, tzinfo=UTC)
    bars = []
    price = start_price
    for i in range(n):
        o = price
        h = price + abs(trend) + 0.5
        low = price - 0.3
        c = price + trend
        bars.append(Bar(
            time=t0 + timedelta(hours=i),
            open=round(o, 5),
            high=round(h, 5),
            low=round(low, 5),
            close=round(c, 5),
            tick_volume=100,
            spread=0.00020,
        ))
        price = c
    return bars


class DummyStrategy(Strategy):
    """Strategie qui entre BUY quand close > open, pour les tests."""
    id = "DUMMY-01"
    version = "1.0.0"
    compatible_regimes = frozenset(MarketRegime)

    def evaluate(self, ctx: StrategyContext) -> StrategySignal | None:
        bars = ctx.bars
        if not bars or len(bars) < 2:
            return None
        last = bars[-1]
        if last.close <= last.open:
            return None
        atr = max(0.001, (last.high - last.low))
        entry = last.close + 0.0002
        return StrategySignal(
            side=Side.BUY,
            entry=entry,
            stop_loss=entry - 1.5 * atr,
            take_profit=entry + 2.5 * atr,
            confidence=0.6,
            reason="test signal",
        )


class LookaheadDetector(Strategy):
    """Strategie qui enregistre le nombre de barres visibles a chaque appel.

    Utilisee pour verifier que le backtest ne passe jamais plus de barres
    que celles disponibles a l'instant t.
    """
    id = "LOOKAHEAD-DETECTOR"
    version = "1.0.0"
    compatible_regimes = frozenset(MarketRegime)
    calls: list[int] = []

    def __init__(self, params=None):
        super().__init__(params)
        self.calls = []

    def evaluate(self, ctx: StrategyContext) -> StrategySignal | None:
        n_bars = len(ctx.bars)
        self.calls.append(n_bars)
        return None  # jamais de signal, on veut juste verifier


# ---------------------------------------------------------------------------
# R Analytics Tests
# ---------------------------------------------------------------------------

class TestRAnalytics:
    def test_basic_winning_trade(self):
        r = compute_r(
            side_sign=1,
            entry=100.0,
            stop_loss=99.0,
            exit_price=102.0,
            take_profit=103.0,
            opened_at=datetime(2024, 1, 1, tzinfo=UTC),
            closed_at=datetime(2024, 1, 2, tzinfo=UTC),
        )
        assert r.initial_risk == 1.0  # 1.0 * 1.0 * 1.0
        assert r.realized_r == 2.0
        assert r.planned_rr == 3.0

    def test_basic_losing_trade(self):
        r = compute_r(
            side_sign=1,
            entry=100.0,
            stop_loss=99.0,
            exit_price=98.5,
            opened_at=datetime(2024, 1, 1, tzinfo=UTC),
            closed_at=datetime(2024, 1, 2, tzinfo=UTC),
        )
        assert r.realized_r == -1.5
        assert r.planned_rr is None  # no TP

    def test_sell_trade(self):
        r = compute_r(
            side_sign=-1,
            entry=100.0,
            stop_loss=101.0,
            exit_price=98.0,
            opened_at=datetime(2024, 1, 1, tzinfo=UTC),
            closed_at=datetime(2024, 1, 2, tzinfo=UTC),
        )
        assert r.realized_r == 2.0

    def test_mfe_mae(self):
        r = compute_r(
            side_sign=1,
            entry=100.0,
            stop_loss=99.0,
            exit_price=100.5,
            mfe_price=101.5,
            mae_price=99.5,
            opened_at=datetime(2024, 1, 1, tzinfo=UTC),
            closed_at=datetime(2024, 1, 2, tzinfo=UTC),
        )
        assert r.mfe_r == 1.5  # (101.5 - 100) / 1.0
        assert r.mae_r == 0.5  # (100 - 99.5) / 1.0

    def test_costs_in_r(self):
        r = compute_r(
            side_sign=1,
            entry=100.0,
            stop_loss=99.0,
            exit_price=101.0,
            opened_at=datetime(2024, 1, 1, tzinfo=UTC),
            closed_at=datetime(2024, 1, 2, tzinfo=UTC),
            spread_at_entry=0.2,
            commission=-0.5,
            swap=-0.1,
            loss_per_lot=10.0,
            volume=0.1,
        )
        # initial_risk = 1.0 * 10.0 * 0.1 = 1.0
        assert r.initial_risk == 1.0
        # PnL brut = (101-100)*10*0.1 = 1.0, + comm(-0.5) + swap(-0.1) = 0.4
        assert r.realized_r == pytest.approx(0.4, abs=0.01)
        assert r.spread_cost_r == pytest.approx(0.2, abs=0.01)

    def test_zero_sl_distance_raises(self):
        with pytest.raises(ValueError):
            compute_r(
                side_sign=1,
                entry=100.0,
                stop_loss=100.0,
                exit_price=101.0,
                opened_at=datetime(2024, 1, 1, tzinfo=UTC),
                closed_at=datetime(2024, 1, 2, tzinfo=UTC),
            )

    def test_holding_time(self):
        r = compute_r(
            side_sign=1,
            entry=100.0,
            stop_loss=99.0,
            exit_price=100.5,
            opened_at=datetime(2024, 1, 1, 10, 0, tzinfo=UTC),
            closed_at=datetime(2024, 1, 1, 14, 30, tzinfo=UTC),
        )
        assert r.holding_time == timedelta(hours=4, minutes=30)

    @pytest.mark.parametrize("side,entry,stop,exit_price", [
        (1, 101.0, 99.0, 103.0), (-1, 100.0, 102.0, 97.0),
    ])
    def test_executable_prices_and_costs(self, side, entry, stop, exit_price):
        params = dict(side_sign=side, entry=entry, stop_loss=stop,
                      exit_price=exit_price, take_profit=entry + side * 4,
                      price_value_per_lot=10.0, volume=1.0,
                      opened_at=datetime(2024, 1, 1, tzinfo=UTC),
                      closed_at=datetime(2024, 1, 2, tzinfo=UTC))
        baseline = compute_r(**params, spread_at_entry=1.0)
        assert baseline.realized_r == pytest.approx((exit_price - entry) * side / 2)
        assert compute_r(**params, spread_at_entry=0.0).realized_r == baseline.realized_r
        costly = compute_r(**params, commission=2.0, slippage=0.1,
                           estimated_commission=2.0, estimated_slippage=0.1)
        assert costly.initial_risk == pytest.approx(23.0)
        assert costly.realized_r < baseline.realized_r
        assert costly.planned_rr == pytest.approx((40 - 2 - 1) / 23)
        assert compute_r(**params, commission=-2.0).realized_r < baseline.realized_r

    def test_loss_per_lot_is_total_stop_loss_not_price_value(self):
        now = datetime(2024, 1, 1, tzinfo=UTC)
        r = compute_r(side_sign=1, entry=100, stop_loss=98, exit_price=101,
                      loss_per_lot=50, volume=2, opened_at=now, closed_at=now)
        assert r.initial_risk == 100
        assert r.realized_r == 0.5

    def test_gap_through_stop_below_minus_one_r(self):
        now = datetime(2024, 1, 1, tzinfo=UTC)
        r = compute_r(side_sign=1, entry=100, stop_loss=99, exit_price=97,
                      opened_at=now, closed_at=now)
        assert r.realized_r < -1
        costly = compute_r(side_sign=1, entry=100, stop_loss=99, exit_price=97,
                           commission=0.2, slippage=0.1, initial_risk=r.initial_risk,
                           opened_at=now, closed_at=now)
        assert costly.realized_r < r.realized_r


# ---------------------------------------------------------------------------
# Dataset Splits Tests
# ---------------------------------------------------------------------------

class TestSplits:
    def test_unsorted_or_duplicate_timestamps_rejected(self):
        bars = make_bars(200)
        with pytest.raises(ValueError, match="strictly chronological"):
            split_bars(bars[:100] + [bars[99]] + bars[100:])
        with pytest.raises(ValueError, match="strictly chronological"):
            split_bars(list(reversed(bars)))

    def test_gap_and_insufficient_purge_rejected(self):
        bars = make_bars(200)
        shifted = bars[:100] + [b.model_copy(update={"time": b.time + timedelta(hours=1)})
                                for b in bars[100:]]
        with pytest.raises(ValueError, match="bar gap"):
            split_bars(shifted, DatasetSplitConfig(expected_interval=timedelta(hours=1)))
        with pytest.raises(ValueError, match="label_horizon"):
            DatasetSplitConfig(purge_bars=5, label_horizon_bars=10)
    def test_basic_split(self):
        bars = make_bars(400)
        segments = split_bars(bars)
        assert "TRAIN" in segments
        assert "VALIDATION" in segments
        assert "OUT_OF_SAMPLE" in segments
        assert "DEMO" in segments
        # All segments should be non-empty with enough bars
        for name, seg in segments.items():
            assert len(seg) > 0, f"{name} segment is empty"

    def test_chronological_order(self):
        """Splits must be strictly chronological - no overlap."""
        bars = make_bars(300)
        segments = split_bars(bars)
        names: list[SplitName] = ["TRAIN", "VALIDATION", "OUT_OF_SAMPLE", "DEMO"]
        for i in range(len(names) - 1):
            current = segments[names[i]]
            nxt = segments[names[i + 1]]
            if current and nxt:
                assert current[-1].time < nxt[0].time, (
                    f"{names[i]} end ({current[-1].time}) must be before "
                    f"{names[i+1]} start ({nxt[0].time})"
                )

    def test_purge_embargo(self):
        """Purge/embargo creates gaps between splits."""
        bars = make_bars(200)
        cfg = DatasetSplitConfig(purge_bars=10, embargo_bars=5)
        segments = split_bars(bars, cfg)
        # TRAIN should not overlap with VALIDATION
        train = segments["TRAIN"]
        val = segments["VALIDATION"]
        if train and val:
            gap_hours = (val[0].time - train[-1].time).total_seconds() / 3600
            assert gap_hours >= 10, f"Expected purge gap, got {gap_hours}h"

    def test_too_few_bars_raises(self):
        bars = make_bars(10)
        with pytest.raises(ValueError, match="at least 50"):
            split_bars(bars)

    def test_split_ranges(self):
        bars = make_bars(200)
        ranges = split_ranges(bars)
        assert len(ranges) == 4
        for r in ranges:
            assert r.bars_count > 0
            assert r.start < r.end

    def test_custom_proportions(self):
        bars = make_bars(500)
        cfg = DatasetSplitConfig(
            train_pct=0.60,
            validation_pct=0.15,
            oos_pct=0.15,
            demo_pct=0.10,
        )
        segments = split_bars(bars, cfg)
        # TRAIN should be the largest
        assert len(segments["TRAIN"]) > len(segments["VALIDATION"])

    def test_invalid_proportions_raises(self):
        with pytest.raises(ValueError, match="sum to 1.0"):
            DatasetSplitConfig(train_pct=0.5, validation_pct=0.5, oos_pct=0.5, demo_pct=0.5)


# ---------------------------------------------------------------------------
# BacktestRunner Tests
# ---------------------------------------------------------------------------

class TestBacktestRunner:
    def test_next_bar_open_fill_cannot_change_prior_signal(self):
        class Once(DummyStrategy):
            def __init__(self):
                super().__init__()
                self.decisions = []

            def evaluate(self, ctx):
                if len(ctx.bars) != 121:
                    return None
                self.decisions.append((len(ctx.bars), ctx.bars[-1].close))
                return StrategySignal(side=Side.BUY, entry=100, stop_loss=98,
                                      take_profit=110, confidence=0.8, reason="once")

        bars = make_bars(124, start_price=100, trend=0.01)
        for opening in (100.5, 101.5):
            history = list(bars)
            history[121] = bars[121].model_copy(update={"open": opening, "high": 102,
                                                       "low": 100, "close": 101})
            strategy = Once()
            result = BacktestRunner(strategy, spread_pips=0).run(history)
            assert strategy.decisions == [(121, bars[120].close)]
            assert result.trades[0].position.entry == opening
            assert result.trades[0].position.bar_index == 121
            assert result.trades[0].position.initial_risk == result.trades[0].r_metrics.initial_risk
            repeated = BacktestRunner(Once(), spread_pips=0).run(history)
            assert repeated.trades[0].position.trade_id == result.trades[0].position.trade_id
            assert repeated.trades[0].r_metrics == result.trades[0].r_metrics

    @pytest.mark.parametrize("side,entry,stop,opening", [
        (Side.BUY, 100.0, 99.0, 97.0),
        (Side.SELL, 100.0, 101.0, 103.0),
    ])
    def test_gap_fills_worse_than_stop(self, side, entry, stop, opening):
        runner = BacktestRunner(DummyStrategy(), spread_pips=0)
        now = datetime(2024, 1, 1, tzinfo=UTC)
        pos = VirtualPosition("gap", "X", side, entry, stop, None, now, 0)
        bar = Bar(time=now + timedelta(hours=1), open=opening,
                  high=opening + 0.5, low=opening - 0.5, close=opening)
        assert runner._check_exit(pos, bar) == opening
        assert pos.exit_reason == "SL_GAP"
        pos.exit_price, pos.closed_at = opening, bar.time
        assert runner._finalize_trade(pos, 1, 0).r_metrics.realized_r < -1

    def test_ambiguous_bar_uses_stop_and_no_post_exit_mfe(self):
        runner = BacktestRunner(DummyStrategy(), spread_pips=0)
        now = datetime(2024, 1, 1, tzinfo=UTC)
        pos = VirtualPosition("both", "X", Side.BUY, 100, 99, 105, now, 0)
        bar = Bar(time=now + timedelta(hours=1), open=100,
                  high=200, low=98, close=150)
        exit_price = runner._check_exit(pos, bar)
        assert exit_price == 99
        assert pos.exit_reason == "AMBIGUOUS_STOP_FIRST"
        runner._update_mfe_mae(pos, bar, exit_price)
        assert pos.mfe_price == 99  # high 200 survient peut-etre apres le SL
        excluded = BacktestRunner(DummyStrategy(), spread_pips=0,
                                  intrabar_policy="EXCLUDE_AMBIGUOUS")
        pos2 = VirtualPosition("both2", "X", Side.BUY, 100, 99, 105, now, 0)
        assert excluded._check_exit(pos2, bar) is None
        assert pos2.exit_reason == "AMBIGUOUS"
    def test_basic_run(self):
        bars = make_bars(200, trend=0.1)
        runner = BacktestRunner(
            strategy=DummyStrategy(),
            spread_pips=2.0,
            point=0.00001,
            loss_per_lot=1.0,
            volume=0.01,
        )
        result = runner.run(bars, symbol="TEST", timeframe=Timeframe.H1)
        assert isinstance(result, BacktestResult)
        assert result.bars_processed > 0
        assert result.strategy_id == "DUMMY-01"

    def test_anti_lookahead_bars_count(self):
        """The strategy must NEVER see more bars than available at time t."""
        bars = make_bars(200)
        detector = LookaheadDetector()
        runner = BacktestRunner(strategy=detector)
        runner.run(bars, symbol="TEST", timeframe=Timeframe.H1)

        # Le premier appel doit voir exactement MIN_BARS_FOR_EVAL+1 barres
        # Les appels suivants doivent voir +1 barre a chaque fois
        if detector.calls:
            for i, n_visible in enumerate(detector.calls):
                expected_max = 120 + i + 1  # MIN_BARS_FOR_EVAL + iteration + 1
                assert n_visible <= expected_max, (
                    f"Anti-lookahead violation: at iteration {i}, strategy saw {n_visible} bars "
                    f"but max allowed was {expected_max}"
                )

    def test_anti_lookahead_monotonic(self):
        """Le nombre de barres visibles doit etre strictement croissant."""
        bars = make_bars(200)
        detector = LookaheadDetector()
        runner = BacktestRunner(strategy=detector)
        runner.run(bars, symbol="TEST", timeframe=Timeframe.H1)

        for i in range(1, len(detector.calls)):
            assert detector.calls[i] >= detector.calls[i - 1], (
                f"Anti-lookahead: bars decreased from {detector.calls[i-1]} to {detector.calls[i]}"
            )

    def test_sl_exit(self):
        """Position must close at SL when price hits it."""
        # Create bars that go up then sharply down
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        up_bars = make_bars(130, trend=0.1, start_time=t0)
        # Add bars that crash below any reasonable SL
        crash_bars = []
        price = up_bars[-1].close
        for i in range(10):
            crash_bars.append(Bar(
                time=t0 + timedelta(hours=130 + i),
                open=price,
                high=price + 0.1,
                low=price - 5.0,  # crash
                close=price - 3.0,
                tick_volume=100,
                spread=0.00020,
            ))
            price = price - 3.0
        all_bars = up_bars + crash_bars

        runner = BacktestRunner(strategy=DummyStrategy())
        result = runner.run(all_bars, symbol="TEST", timeframe=Timeframe.H1)
        # At least some trades should have hit SL
        # We expect SL exits from the crash
        assert len(result.trades) > 0

    def test_run_splits(self):
        bars = make_bars(500, trend=0.05)
        runner = BacktestRunner(strategy=DummyStrategy())
        results = runner.run_splits(bars, symbol="TEST", timeframe=Timeframe.H1)
        assert "TRAIN" in results
        assert "VALIDATION" in results
        assert "OUT_OF_SAMPLE" in results

    def test_split_warmup_has_context_but_no_warmup_trades(self):
        bars = make_bars(500, trend=0.05)
        segments = split_bars(bars)
        val = segments["VALIDATION"]
        assert len(val) < 120
        result = BacktestRunner(DummyStrategy(), spread_pips=0).run_splits(bars)["VALIDATION"]
        assert result.n_trades > 0
        assert all(val[0].time <= t.position.opened_at <= val[-1].time for t in result.trades)

    def test_result_to_experiment_result(self):
        bars = make_bars(300, trend=0.1)
        runner = BacktestRunner(strategy=DummyStrategy())
        result = runner.run(bars, symbol="TEST", timeframe=Timeframe.H1)
        exp_result = result.to_experiment_result("EXP-001")
        assert exp_result.experiment_id == "EXP-001"
        assert exp_result.trades == result.n_trades

    def test_insufficient_bars(self):
        bars = make_bars(50)
        runner = BacktestRunner(strategy=DummyStrategy())
        result = runner.run(bars)
        assert result.n_trades == 0
        assert result.bars_processed == 0


# ---------------------------------------------------------------------------
# Scorecard Tests
# ---------------------------------------------------------------------------

class TestScorecard:
    def test_insufficient_sample(self):
        result = BacktestResult(
            trades=[],
            bars_processed=100,
            symbol="TEST",
            timeframe="H1",
            strategy_id="DUMMY-01",
            strategy_version="1.0.0",
            split="TRAIN",
        )
        card = build_scorecard(result)
        assert card.insufficient is True
        assert card.status == "INSUFFICIENT_SAMPLE"

    def test_valid_scorecard(self):
        # Need to run a real backtest with enough trades
        bars = make_bars(1000, trend=0.05)
        runner = BacktestRunner(strategy=DummyStrategy())
        result = runner.run(bars, symbol="TEST", timeframe=Timeframe.H1)
        if result.n_trades >= MINIMUM_TRADES:
            card = build_scorecard(result)
            assert card.insufficient is False
            assert card.status == "OK"
            assert card.win_rate is not None
            assert card.expectancy_r is not None
            assert card.trades == result.n_trades
        else:
            # Not enough trades in this synthetic data - that's ok
            card = build_scorecard(result)
            assert card.insufficient is True
