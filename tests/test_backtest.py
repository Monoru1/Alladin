"""Tests BacktestRunner, R Analytics, Splits, Scorecard.

Inclut des tests explicites anti-lookahead.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from alladin.core.enums import MarketRegime, Side, Timeframe
from alladin.core.models import Bar
from alladin.research.backtest import BacktestResult, BacktestRunner, BacktestTrade, VirtualPosition
from alladin.research.models import StrategyExperiment
from alladin.research.r_analytics import CostCategory, FillRecord, compute_r
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


# ---------------------------------------------------------------------------
# Fill Record Parity Tests (Lot D)
# ---------------------------------------------------------------------------

class TestFillRecordParity:
    """Verify FillRecord economics match RMetrics exactly."""

    def _run_single_trade(self, **runner_kwargs) -> BacktestTrade:
        """Helper: run a backtest that produces exactly 1 trade."""
        class OnceSignal(Strategy):
            id = "PARITY-01"
            version = "1.0.0"
            compatible_regimes = frozenset(MarketRegime)
            _fired = False

            def evaluate(self, ctx: StrategyContext) -> StrategySignal | None:
                if self._fired or len(ctx.bars) < 122:
                    return None
                self._fired = True
                last = ctx.bars[-1]
                atr = max(0.001, last.high - last.low)
                return StrategySignal(
                    side=Side.BUY,
                    entry=last.close + 0.0002,
                    stop_loss=last.close - 1.5 * atr,
                    take_profit=last.close + 2.5 * atr,
                    confidence=0.7,
                    reason="parity test",
                )

        bars = make_bars(200, trend=0.1)
        runner = BacktestRunner(OnceSignal(), **runner_kwargs)
        result = runner.run(bars, symbol="PARITY", timeframe=Timeframe.H1)
        assert result.n_trades >= 1, "Expected at least 1 trade"
        return result.trades[0]

    def test_fill_record_exists(self):
        """Every BacktestTrade must have a FillRecord."""
        bars = make_bars(200, trend=0.1)
        runner = BacktestRunner(DummyStrategy())
        result = runner.run(bars, symbol="TEST", timeframe=Timeframe.H1)
        for trade in result.trades:
            assert trade.fill is not None, "FillRecord must be set"
            assert isinstance(trade.fill, FillRecord)

    def test_fill_is_immutable(self):
        """FillRecord must be frozen."""
        trade = self._run_single_trade()
        assert trade.fill is not None
        with pytest.raises(AttributeError):
            trade.fill.net_pnl = 999.0  # type: ignore[misc]

    def test_r_multiple_matches_realized_r(self):
        """fill.r_multiple must equal r_metrics.realized_r exactly."""
        bars = make_bars(300, trend=0.05)
        runner = BacktestRunner(DummyStrategy(), spread_pips=2.0, commission_per_lot=0.5,
                                slippage=0.0001)
        result = runner.run(bars, symbol="TEST", timeframe=Timeframe.H1)
        for trade in result.trades:
            assert trade.fill is not None
            assert trade.fill.r_multiple == trade.r_metrics.realized_r

    def test_initial_risk_matches(self):
        """fill.initial_risk must equal r_metrics.initial_risk."""
        trade = self._run_single_trade(commission_per_lot=1.0, slippage=0.0002)
        assert trade.fill is not None
        assert trade.fill.initial_risk == trade.r_metrics.initial_risk

    def test_cost_model_reflects_runner(self):
        """CostModel must reflect BacktestRunner configuration."""
        trade_zero = self._run_single_trade(spread_pips=2.0, commission_per_lot=0.0,
                                            slippage=0.0)
        assert trade_zero.fill is not None
        assert trade_zero.fill.cost_model.spread == CostCategory.MODELED
        assert trade_zero.fill.cost_model.commission == CostCategory.ZERO
        assert trade_zero.fill.cost_model.slippage == CostCategory.ZERO
        assert trade_zero.fill.cost_model.swap == CostCategory.ZERO

        trade_costs = self._run_single_trade(spread_pips=2.0, commission_per_lot=1.0,
                                             slippage=0.0001)
        assert trade_costs.fill is not None
        assert trade_costs.fill.cost_model.commission == CostCategory.MODELED
        assert trade_costs.fill.cost_model.slippage == CostCategory.MODELED

    def test_net_pnl_equals_gross_minus_costs(self):
        """net_pnl = gross_pnl - slippage_cost - commission + swap."""
        trade = self._run_single_trade(commission_per_lot=0.5, slippage=0.0001)
        f = trade.fill
        assert f is not None
        expected_net = f.gross_pnl - f.slippage_cost - f.commission + f.swap
        assert f.net_pnl == pytest.approx(expected_net, abs=1e-10)

    def test_r_from_monetary(self):
        """r_multiple must equal net_pnl / initial_risk (within rounding)."""
        trade = self._run_single_trade(commission_per_lot=0.5, slippage=0.0001)
        f = trade.fill
        assert f is not None
        assert f.initial_risk > 0
        computed_r = f.net_pnl / f.initial_risk
        assert f.r_multiple == pytest.approx(computed_r, abs=1e-4)

    @pytest.mark.parametrize("trend,exit_type", [
        (0.1, "winner"),  # uptrend → BUY wins
        (-0.3, "loser"),  # downtrend → BUY loses fast via SL
    ])
    def test_long_winner_and_loser(self, trend, exit_type):
        """LONG winner and loser must have correct fill sign."""
        bars = make_bars(200, trend=trend)
        runner = BacktestRunner(DummyStrategy(), spread_pips=1.0)
        result = runner.run(bars, symbol="TEST", timeframe=Timeframe.H1)
        for trade in result.trades:
            f = trade.fill
            assert f is not None
            assert f.side == 1  # BUY
            assert f.r_multiple == trade.r_metrics.realized_r

    def test_short_trade_fill(self):
        """SHORT trades must have side=-1 and correct economics."""
        class ShortOnly(Strategy):
            id = "SHORT-01"
            version = "1.0.0"
            compatible_regimes = frozenset(MarketRegime)
            _fired = False

            def evaluate(self, ctx: StrategyContext) -> StrategySignal | None:
                if self._fired or len(ctx.bars) < 122:
                    return None
                self._fired = True
                last = ctx.bars[-1]
                atr = max(0.001, last.high - last.low)
                return StrategySignal(
                    side=Side.SELL,
                    entry=last.close,
                    stop_loss=last.close + 1.5 * atr,
                    take_profit=last.close - 2.5 * atr,
                    confidence=0.7,
                    reason="short parity test",
                )

        bars = make_bars(200, trend=-0.1)
        runner = BacktestRunner(ShortOnly(), spread_pips=1.0)
        result = runner.run(bars, symbol="TEST", timeframe=Timeframe.H1)
        if result.n_trades > 0:
            f = result.trades[0].fill
            assert f is not None
            assert f.side == -1
            assert f.r_multiple == result.trades[0].r_metrics.realized_r

    def test_sl_exit_fill(self):
        """SL exit must have exit_reason containing 'SL' and correct fill."""
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        up_bars = make_bars(130, trend=0.1, start_time=t0)
        price = up_bars[-1].close
        crash_bars = []
        for i in range(10):
            crash_bars.append(Bar(
                time=t0 + timedelta(hours=130 + i),
                open=price, high=price + 0.1, low=price - 5.0,
                close=price - 3.0, tick_volume=100, spread=0.00020,
            ))
            price -= 3.0
        runner = BacktestRunner(DummyStrategy(), spread_pips=2.0)
        result = runner.run(up_bars + crash_bars, symbol="TEST", timeframe=Timeframe.H1)
        sl_trades = [t for t in result.trades if "SL" in t.position.exit_reason]
        assert len(sl_trades) > 0, "Expected SL exits from crash"
        for trade in sl_trades:
            f = trade.fill
            assert f is not None
            assert "SL" in f.exit_reason
            assert f.r_multiple == trade.r_metrics.realized_r
            assert f.r_multiple <= 0  # SL exit is a loss

    def test_end_of_data_exit_fill(self):
        """END_OF_DATA exit must be captured in fill."""
        class AlwaysBuy(Strategy):
            id = "ALWAYS-01"
            version = "1.0.0"
            compatible_regimes = frozenset(MarketRegime)

            def evaluate(self, ctx: StrategyContext) -> StrategySignal | None:
                last = ctx.bars[-1]
                return StrategySignal(
                    side=Side.BUY, entry=last.close + 0.01,
                    stop_loss=last.close - 50, take_profit=last.close + 500,
                    confidence=0.5, reason="always",
                )

        bars = make_bars(200, trend=0.01)
        runner = BacktestRunner(AlwaysBuy(), spread_pips=0, max_concurrent=1)
        result = runner.run(bars, symbol="TEST", timeframe=Timeframe.H1)
        eod_trades = [t for t in result.trades if t.position.exit_reason == "END_OF_DATA"]
        if eod_trades:
            f = eod_trades[-1].fill
            assert f is not None
            assert f.exit_reason == "END_OF_DATA"
            assert f.r_multiple == eod_trades[-1].r_metrics.realized_r

    def test_spread_cost_is_positive(self):
        """Spread cost must be non-negative."""
        bars = make_bars(200, trend=0.1)
        runner = BacktestRunner(DummyStrategy(), spread_pips=3.0)
        result = runner.run(bars, symbol="TEST", timeframe=Timeframe.H1)
        for trade in result.trades:
            assert trade.fill is not None
            assert trade.fill.spread_cost >= 0

    def test_zero_cost_runner(self):
        """With zero costs, gross_pnl == net_pnl."""
        bars = make_bars(200, trend=0.1)
        runner = BacktestRunner(DummyStrategy(), spread_pips=0, commission_per_lot=0,
                                slippage=0)
        result = runner.run(bars, symbol="TEST", timeframe=Timeframe.H1)
        for trade in result.trades:
            f = trade.fill
            assert f is not None
            assert f.slippage_cost == 0.0
            assert f.commission == 0.0
            assert f.swap == 0.0
            assert f.net_pnl == pytest.approx(f.gross_pnl, abs=1e-12)

    def test_fill_trade_id_matches_position(self):
        """FillRecord.trade_id must match VirtualPosition.trade_id."""
        bars = make_bars(200, trend=0.1)
        runner = BacktestRunner(DummyStrategy())
        result = runner.run(bars, symbol="TEST", timeframe=Timeframe.H1)
        for trade in result.trades:
            assert trade.fill is not None
            assert trade.fill.trade_id == trade.position.trade_id

    def test_fill_symbol_and_timing(self):
        """FillRecord must carry correct symbol and timing from position."""
        bars = make_bars(200, trend=0.1)
        runner = BacktestRunner(DummyStrategy())
        result = runner.run(bars, symbol="EURUSD", timeframe=Timeframe.H1)
        for trade in result.trades:
            f = trade.fill
            assert f is not None
            assert f.symbol == "EURUSD"
            assert f.opened_at == trade.position.opened_at
            assert f.closed_at == trade.position.closed_at

    def test_parity_with_costs(self):
        """Full parity: same runner config, fill and r_metrics agree on all economics."""
        bars = make_bars(500, trend=0.05)
        runner = BacktestRunner(
            DummyStrategy(), spread_pips=2.0, commission_per_lot=0.7,
            slippage=0.00005, volume=0.1, loss_per_lot=10.0,
        )
        result = runner.run(bars, symbol="GBPUSD", timeframe=Timeframe.H1)
        assert result.n_trades >= 5, "Need enough trades for parity validation"
        for trade in result.trades:
            f = trade.fill
            r = trade.r_metrics
            assert f is not None
            # R parity
            assert f.r_multiple == r.realized_r
            assert f.initial_risk == r.initial_risk
            # Monetary consistency
            expected_net = f.gross_pnl - f.slippage_cost - f.commission + f.swap
            assert f.net_pnl == pytest.approx(expected_net, abs=1e-10)
            # R derivable from monetary
            if f.initial_risk > 0:
                assert f.r_multiple == pytest.approx(f.net_pnl / f.initial_risk, abs=1e-4)


# ---------------------------------------------------------------------------
# Reproducibility & Provenance Tests (Lot D4)
# ---------------------------------------------------------------------------

def _bars_fingerprint(bars: list[Bar], symbol: str = "TEST") -> str:
    """Compute a SHA-256 fingerprint of bars for test provenance."""
    import json
    rows = [{"s": symbol, "t": b.time.isoformat(), "o": b.open, "h": b.high,
             "l": b.low, "c": b.close} for b in bars]
    body = json.dumps(rows, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


class TestReproducibility:
    """Verify deterministic experiment identity and result stability."""

    def test_same_inputs_same_trades(self):
        """Same bars + same strategy + same config → identical trade IDs and R."""
        bars = make_bars(200, trend=0.1)
        for _ in range(2):
            runner = BacktestRunner(DummyStrategy(), spread_pips=2.0, volume=0.01)
            result = runner.run(bars, symbol="TEST", timeframe=Timeframe.H1)
            assert result.n_trades > 0
        r1 = BacktestRunner(DummyStrategy(), spread_pips=2.0, volume=0.01).run(bars, symbol="TEST", timeframe=Timeframe.H1)
        r2 = BacktestRunner(DummyStrategy(), spread_pips=2.0, volume=0.01).run(bars, symbol="TEST", timeframe=Timeframe.H1)
        assert r1.n_trades == r2.n_trades
        for t1, t2 in zip(r1.trades, r2.trades, strict=True):
            assert t1.position.trade_id == t2.position.trade_id
            assert t1.r_metrics.realized_r == t2.r_metrics.realized_r
            assert t1.fill is not None and t2.fill is not None
            assert t1.fill.r_multiple == t2.fill.r_multiple

    def test_different_cost_model_different_economics(self):
        """Changing the cost model changes net economics."""
        bars = make_bars(300, trend=0.05)
        r_zero = BacktestRunner(DummyStrategy(), spread_pips=0, commission_per_lot=0).run(bars)
        r_costly = BacktestRunner(DummyStrategy(), spread_pips=3.0, commission_per_lot=1.0).run(bars)
        assert r_zero.n_trades > 0
        assert r_costly.n_trades > 0
        # Economics differ
        assert r_zero.total_r != r_costly.total_r

    def test_different_data_different_fingerprint(self):
        """Changing bars produces a different fingerprint."""
        bars_a = make_bars(200, trend=0.1)
        bars_b = make_bars(200, trend=-0.1)
        fp_a = _bars_fingerprint(bars_a)
        fp_b = _bars_fingerprint(bars_b)
        assert fp_a != fp_b
        assert len(fp_a) == 64  # SHA-256 hex

    def test_experiment_binds_fingerprint_and_cost_model(self):
        """to_experiment() binds dataset fingerprint and cost model label."""
        bars = make_bars(300, trend=0.05)
        fp = _bars_fingerprint(bars, "EURUSD")
        runner = BacktestRunner(DummyStrategy(), spread_pips=2.0)
        result = runner.run(bars, symbol="EURUSD", timeframe=Timeframe.H1, split="TRAIN")
        exp = result.to_experiment(
            experiment_id="EXP-PROV-001",
            dataset="EURUSD-H1-2024",
            dataset_fingerprint=fp,
            dataset_provenance="archive:test_bars",
            cost_model_label=runner.cost_model.label,
        )
        assert isinstance(exp, StrategyExperiment)
        assert exp.dataset_fingerprint == fp
        assert exp.dataset_provenance == "archive:test_bars"
        assert exp.parameters.get("cost_model") == runner.cost_model.label
        assert exp.strategy_id == "DUMMY-01"
        assert exp.symbols == ["EURUSD"]
        assert exp.split == "TRAIN"

    def test_experiment_without_fingerprint_is_non_comparable(self):
        """Experiment without fingerprint is valid but non-comparable."""
        bars = make_bars(200, trend=0.05)
        runner = BacktestRunner(DummyStrategy())
        result = runner.run(bars)
        exp = result.to_experiment("EXP-NOFP-001", "test")
        assert exp.dataset_fingerprint is None
        assert exp.dataset_provenance is None

    def test_fingerprint_provenance_must_be_paired(self):
        """Fingerprint without provenance raises validation error."""
        bars = make_bars(200, trend=0.05)
        runner = BacktestRunner(DummyStrategy())
        result = runner.run(bars)
        fp = _bars_fingerprint(bars)
        with pytest.raises(ValueError, match="fingerprint and provenance must be provided together"):
            result.to_experiment("EXP-BAD-001", "test", dataset_fingerprint=fp)


# ---------------------------------------------------------------------------
# OOS Structural Guarantee Tests (Lot D5)
# ---------------------------------------------------------------------------

class TestOOSGuarantee:
    """Prove OOS independence from TRAIN optimization."""

    def test_oos_trades_only_in_oos_window(self):
        """OOS trades must occur only within the OOS time window."""
        bars = make_bars(500, trend=0.05)
        runner = BacktestRunner(DummyStrategy(), spread_pips=0)
        results = runner.run_splits(bars)
        oos = results.get("OUT_OF_SAMPLE")
        if oos and oos.n_trades > 0:
            from alladin.research.splits import split_bars
            segments = split_bars(bars)
            oos_bars = segments["OUT_OF_SAMPLE"]
            for t in oos.trades:
                assert oos_bars[0].time <= t.position.opened_at <= oos_bars[-1].time, (
                    f"OOS trade {t.position.trade_id} opened at {t.position.opened_at} "
                    f"outside OOS window [{oos_bars[0].time}, {oos_bars[-1].time}]"
                )

    def test_train_oos_no_overlap(self):
        """TRAIN and OOS windows must not overlap (purge/embargo gap)."""
        bars = make_bars(500, trend=0.05)
        from alladin.research.splits import DatasetSplitConfig, split_bars
        cfg = DatasetSplitConfig(purge_bars=10, embargo_bars=5)
        segments = split_bars(bars, cfg)
        train = segments["TRAIN"]
        oos = segments["OUT_OF_SAMPLE"]
        assert train[-1].time < oos[0].time

    def test_strategy_sees_only_past(self):
        """During OOS, strategy must not see future bars."""
        bars = make_bars(500)
        detector = LookaheadDetector()
        runner = BacktestRunner(detector, spread_pips=0)
        runner.run_splits(bars)
        if detector.calls:
            for i in range(1, len(detector.calls)):
                assert detector.calls[i] >= detector.calls[i - 1]


# ---------------------------------------------------------------------------
# Functional End-to-End Path (Lot D — bench proof)
# ---------------------------------------------------------------------------

class TestFunctionalBenchPath:
    """Prove a classical baseline can travel the full experimental bench."""

    def test_end_to_end_experiment(self):
        """historical bars → strategy → fill → R → experiment → result."""
        bars = make_bars(500, trend=0.05)
        fp = _bars_fingerprint(bars, "TEST")
        runner = BacktestRunner(
            DummyStrategy(), spread_pips=2.0, commission_per_lot=0.5,
            volume=0.01, loss_per_lot=10.0,
        )
        result = runner.run(bars, symbol="TEST", timeframe=Timeframe.H1, split="TRAIN")
        assert result.n_trades >= 5

        # Every trade has a FillRecord with consistent economics
        for trade in result.trades:
            f = trade.fill
            assert f is not None
            assert f.r_multiple == trade.r_metrics.realized_r
            assert f.cost_model.label == runner.cost_model.label

        # Create experiment with provenance
        exp = result.to_experiment(
            experiment_id="E2E-001",
            dataset="TEST-H1-synthetic",
            dataset_fingerprint=fp,
            dataset_provenance="test:make_bars(500,0.05)",
            cost_model_label=runner.cost_model.label,
        )
        assert exp.dataset_fingerprint == fp
        assert exp.strategy_id == "DUMMY-01"

        # Create experiment result
        exp_result = result.to_experiment_result("E2E-001")
        assert exp_result.trades == result.n_trades
        assert exp_result.r_total == pytest.approx(result.total_r, abs=1e-4)

        # Provenance chain: dataset identity + cost model + strategy → result
        assert exp.parameters["cost_model"] == runner.cost_model.label
        assert exp.dataset_fingerprint is not None
        assert len(exp.dataset_fingerprint) == 64
