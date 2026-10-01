"""BacktestRunner : simulation offline d'une strategie sur donnees historiques.

Pipeline :
    MarketDataArchive -> bars -> split -> chronological iteration ->
    MarketQualityEngine (stub) -> RegimeClassifier -> Strategy evaluation ->
    Opportunity -> virtual position -> bar-by-bar evolution -> exit ->
    R analytics -> ExperimentResult -> ResearchRepository

PROPRIETE ABSOLUE : a l'instant t, la strategie ne peut JAMAIS lire t+1.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from alladin.core.enums import MarketRegime, Side, Timeframe
from alladin.core.models import Bar
from alladin.market.regime import RegimeClassifier, primary_metrics
from alladin.research.models import ExperimentResult
from alladin.research.r_analytics import RMetrics, compute_r
from alladin.research.splits import DatasetSplitConfig, SplitName, split_bars
from alladin.strategies.base import Strategy, StrategyContext, StrategySignal

log = logging.getLogger(__name__)

MIN_BARS_FOR_EVAL = 120  # barres minimum avant premiere evaluation


@dataclass
class VirtualPosition:
    """Position virtuelle trackee bar par bar."""

    trade_id: str
    symbol: str
    side: Side
    entry: float
    stop_loss: float
    take_profit: float | None
    opened_at: datetime
    bar_index: int  # index dans la serie (pour anti-lookahead audit)
    confidence: float = 0.0
    reason: str = ""
    regime: MarketRegime = MarketRegime.UNKNOWN

    # Filled during simulation
    exit_price: float | None = None
    closed_at: datetime | None = None
    exit_reason: str = ""
    mfe_price: float | None = None  # prix au MFE
    mae_price: float | None = None  # prix au MAE

    @property
    def is_open(self) -> bool:
        return self.exit_price is None


@dataclass
class BacktestTrade:
    """Trade complet avec R metrics."""

    position: VirtualPosition
    r_metrics: RMetrics
    bars_held: int = 0


@dataclass
class BacktestResult:
    """Resultat complet d'un backtest."""

    trades: list[BacktestTrade] = field(default_factory=list)
    rejected_signals: int = 0
    bars_processed: int = 0
    symbol: str = ""
    timeframe: str = ""
    strategy_id: str = ""
    strategy_version: str = ""
    split: str = ""
    period_start: datetime | None = None
    period_end: datetime | None = None

    @property
    def n_trades(self) -> int:
        return len(self.trades)

    @property
    def wins(self) -> int:
        return sum(1 for t in self.trades if t.r_metrics.realized_r > 0)

    @property
    def losses(self) -> int:
        return sum(1 for t in self.trades if t.r_metrics.realized_r <= 0)

    @property
    def win_rate(self) -> float | None:
        return self.wins / self.n_trades if self.n_trades else None

    @property
    def expectancy_r(self) -> float | None:
        if not self.trades:
            return None
        return sum(t.r_metrics.realized_r for t in self.trades) / self.n_trades

    @property
    def total_r(self) -> float:
        return sum(t.r_metrics.realized_r for t in self.trades)

    @property
    def profit_factor(self) -> float | None:
        gross_win = sum(t.r_metrics.realized_r for t in self.trades if t.r_metrics.realized_r > 0)
        gross_loss = abs(sum(t.r_metrics.realized_r for t in self.trades if t.r_metrics.realized_r <= 0))
        if gross_loss == 0:
            return None
        return gross_win / gross_loss

    @property
    def max_drawdown_r(self) -> float:
        if not self.trades:
            return 0.0
        equity = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in self.trades:
            equity += t.r_metrics.realized_r
            if equity > peak:
                peak = equity
            dd = peak - equity
            if dd > max_dd:
                max_dd = dd
        return max_dd

    def to_experiment_result(self, experiment_id: str) -> ExperimentResult:
        return ExperimentResult(
            experiment_id=experiment_id,
            trades=self.n_trades,
            wins=self.wins,
            losses=self.losses,
            win_rate=self.win_rate,
            expectancy=self.expectancy_r,
            profit_factor=self.profit_factor,
            max_drawdown=self.max_drawdown_r,
            r_total=self.total_r,
            sharpe=None,  # TODO: ajouter si necessaire
            passed=self.n_trades >= 30 and (self.expectancy_r or 0) > 0,
        )


class BacktestRunner:
    """Execute un backtest strictement chronologique.

    Anti-lookahead garanti : la strategie recoit UNIQUEMENT bars[:i+1] a l'instant i.
    """

    def __init__(
        self,
        strategy: Strategy,
        classifier: RegimeClassifier | None = None,
        *,
        spread_pips: float = 2.0,
        commission_per_lot: float = 0.0,
        point: float = 0.00001,
        loss_per_lot: float = 1.0,
        volume: float = 0.01,
        max_concurrent: int = 1,
    ) -> None:
        self.strategy = strategy
        self.classifier = classifier or RegimeClassifier()
        self.spread_pips = spread_pips
        self.commission = commission_per_lot
        self.point = point
        self.loss_per_lot = loss_per_lot
        self.volume = volume
        self.max_concurrent = max_concurrent

    def run(
        self,
        bars: list[Bar],
        symbol: str = "UNKNOWN",
        timeframe: Timeframe = Timeframe.H1,
        split: SplitName = "TRAIN",
    ) -> BacktestResult:
        """Execute le backtest bar par bar. Strictement chronologique."""
        result = BacktestResult(
            symbol=symbol,
            timeframe=timeframe.value,
            strategy_id=self.strategy.id,
            strategy_version=self.strategy.version,
            split=split,
        )

        if len(bars) < MIN_BARS_FOR_EVAL:
            log.warning("Not enough bars for backtest: %d < %d", len(bars), MIN_BARS_FOR_EVAL)
            return result

        result.period_start = bars[0].time
        result.period_end = bars[-1].time

        open_positions: list[VirtualPosition] = []
        spread = self.spread_pips * self.point

        for i in range(MIN_BARS_FOR_EVAL, len(bars)):
            result.bars_processed += 1

            # ANTI-LOOKAHEAD : la strategie voit UNIQUEMENT bars[0:i+1] (inclus i, excluant futur)
            visible_bars = bars[:i + 1]
            current_bar = bars[i]

            # 1. Update open positions avec la barre courante
            newly_closed: list[tuple[VirtualPosition, int]] = []
            for pos in list(open_positions):
                self._update_mfe_mae(pos, current_bar)
                exit_price = self._check_exit(pos, current_bar)
                if exit_price is not None:
                    pos.exit_price = exit_price
                    pos.closed_at = current_bar.time
                    bars_held = i - pos.bar_index
                    newly_closed.append((pos, bars_held))

            for pos, bars_held in newly_closed:
                open_positions.remove(pos)
                trade = self._finalize_trade(pos, bars_held, spread)
                result.trades.append(trade)

            # 2. Evaluate strategy si pas de position ouverte (ou max_concurrent pas atteint)
            if len(open_positions) < self.max_concurrent:
                signal = self._evaluate_strategy(visible_bars, symbol, timeframe)
                if signal is not None:
                    # Entry sur la PROCHAINE barre (pas la courante) si on est strict
                    # Ici on entre sur la barre courante a l'open comme approximation
                    pos = VirtualPosition(
                        trade_id=f"BT-{uuid4().hex[:8]}",
                        symbol=symbol,
                        side=signal.side,
                        entry=signal.entry,
                        stop_loss=signal.stop_loss,
                        take_profit=signal.take_profit,
                        opened_at=current_bar.time,
                        bar_index=i,
                        confidence=signal.confidence,
                        reason=signal.reason,
                    )
                    open_positions.append(pos)
                else:
                    result.rejected_signals += 1

        # Close remaining positions at last bar
        if open_positions:
            last_bar = bars[-1]
            for pos in open_positions:
                exit_p = last_bar.close
                pos.exit_price = exit_p
                pos.closed_at = last_bar.time
                pos.exit_reason = "END_OF_DATA"
                bars_held = len(bars) - 1 - pos.bar_index
                trade = self._finalize_trade(pos, bars_held, spread)
                result.trades.append(trade)

        return result

    def run_splits(
        self,
        all_bars: list[Bar],
        symbol: str = "UNKNOWN",
        timeframe: Timeframe = Timeframe.H1,
        config: DatasetSplitConfig | None = None,
    ) -> dict[SplitName, BacktestResult]:
        """Execute le backtest sur chaque split independamment."""
        segments = split_bars(all_bars, config)
        results: dict[SplitName, BacktestResult] = {}
        for split_name, split_bars_list in segments.items():
            results[split_name] = self.run(split_bars_list, symbol, timeframe, split_name)
        return results

    def _evaluate_strategy(
        self,
        visible_bars: list[Bar],
        symbol: str,
        timeframe: Timeframe,
    ) -> StrategySignal | None:
        """Evaluate la strategie avec seulement les barres visibles."""
        # Regime classification sur barres visibles
        assessment = self.classifier.classify(visible_bars)
        if not self.strategy.is_compatible(assessment.regime):
            return None

        metrics = primary_metrics(visible_bars)
        if metrics is None:
            return None

        # Construire un ScanCandidate minimal pour le StrategyContext
        from alladin.core.enums import AssetCategory
        from alladin.core.models import Tick
        from alladin.market.models import ScanCandidate

        last_bar = visible_bars[-1]
        spread = self.spread_pips * self.point
        tick = Tick(
            symbol=symbol,
            time=last_bar.time,
            bid=last_bar.close,
            ask=last_bar.close + spread,
        )

        cand = ScanCandidate(
            symbol=symbol,
            category=AssetCategory.OTHER,
            regime=assessment.regime,
            regime_confidence=assessment.confidence,
            regime_reasons=assessment.reasons,
            score=0.5,
            session="BACKTEST",
            spread_points=spread / self.point,
            spread_atr_ratio=spread / metrics["atr"] if metrics.get("atr", 0) > 0 else 9.9,
            metrics=metrics,
            tf_trend={},
            spec=None,
            tick=tick,
            bars={timeframe: visible_bars},
        )

        ctx = StrategyContext(
            run_id="backtest",
            now=last_bar.time if last_bar.time.tzinfo else last_bar.time.replace(tzinfo=UTC),
            candidate=cand,
        )
        return self.strategy.evaluate(ctx)

    def _update_mfe_mae(self, pos: VirtualPosition, bar: Bar) -> None:
        """Met a jour MFE/MAE en prix."""
        if pos.side == Side.BUY:
            favorable = bar.high
            adverse = bar.low
            if pos.mfe_price is None or favorable > pos.mfe_price:
                pos.mfe_price = favorable
            if pos.mae_price is None or adverse < pos.mae_price:
                pos.mae_price = adverse
        else:
            favorable = bar.low
            adverse = bar.high
            if pos.mfe_price is None or favorable < pos.mfe_price:
                pos.mfe_price = favorable
            if pos.mae_price is None or adverse > pos.mae_price:
                pos.mae_price = adverse

    def _check_exit(self, pos: VirtualPosition, bar: Bar) -> float | None:
        """Verifie si SL ou TP touche sur la barre courante. Retourne exit_price ou None."""
        if pos.side == Side.BUY:
            if bar.low <= pos.stop_loss:
                pos.exit_reason = "SL"
                return pos.stop_loss
            if pos.take_profit is not None and bar.high >= pos.take_profit:
                pos.exit_reason = "TP"
                return pos.take_profit
        else:  # SELL
            if bar.high >= pos.stop_loss:
                pos.exit_reason = "SL"
                return pos.stop_loss
            if pos.take_profit is not None and bar.low <= pos.take_profit:
                pos.exit_reason = "TP"
                return pos.take_profit
        return None

    def _finalize_trade(self, pos: VirtualPosition, bars_held: int, spread: float) -> BacktestTrade:
        """Finalise un trade et calcule les R metrics."""
        assert pos.exit_price is not None
        assert pos.closed_at is not None

        r_metrics = compute_r(
            side_sign=1 if pos.side == Side.BUY else -1,
            entry=pos.entry,
            stop_loss=pos.stop_loss,
            exit_price=pos.exit_price,
            take_profit=pos.take_profit,
            mfe_price=pos.mfe_price,
            mae_price=pos.mae_price,
            opened_at=pos.opened_at,
            closed_at=pos.closed_at,
            spread_at_entry=spread,
            slippage=0.0,
            commission=self.commission * self.volume,
            swap=0.0,
            loss_per_lot=self.loss_per_lot,
            volume=self.volume,
        )
        return BacktestTrade(
            position=pos,
            r_metrics=r_metrics,
            bars_held=bars_held,
        )
