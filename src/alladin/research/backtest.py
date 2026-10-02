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
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from alladin.core.enums import MarketRegime, Side, Timeframe
from alladin.core.models import Bar
from alladin.market.regime import RegimeClassifier, primary_metrics
from alladin.research.models import ExperimentResult, StrategyExperiment
from alladin.research.r_analytics import CostCategory, CostModel, FillRecord, RMetrics, compute_r
from alladin.research.splits import DatasetSplitConfig, SplitName, split_bars
from alladin.strategies.base import Strategy, StrategyContext, StrategySignal

log = logging.getLogger(__name__)

MIN_BARS_FOR_EVAL = 120  # barres minimum avant premiere evaluation
IntrabarPolicy = Literal["CONSERVATIVE_STOP_FIRST", "EXCLUDE_AMBIGUOUS"]


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
    initial_risk: float | None = None

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
    """Trade complet avec R metrics et fill record."""

    position: VirtualPosition
    r_metrics: RMetrics
    fill: FillRecord | None = None
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
    intrabar_policy: str = "CONSERVATIVE_STOP_FIRST"
    ambiguous_positions: list[VirtualPosition] = field(default_factory=list)

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

    def to_experiment(
        self,
        experiment_id: str,
        dataset: str,
        *,
        dataset_fingerprint: str | None = None,
        dataset_provenance: str | None = None,
        cost_model_label: str = "",
    ) -> StrategyExperiment:
        """Create a StrategyExperiment bound to this result's provenance.

        The caller must provide dataset_fingerprint/provenance from the
        archive that produced the bars. This is the explicit required
        boundary between research and archival systems.
        """
        params: dict[str, object] = {}
        if cost_model_label:
            params["cost_model"] = cost_model_label
        return StrategyExperiment(
            experiment_id=experiment_id,
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
            dataset=dataset,
            dataset_fingerprint=dataset_fingerprint,
            dataset_provenance=dataset_provenance,
            period_start=self.period_start or datetime(2000, 1, 1, tzinfo=UTC),
            period_end=self.period_end or datetime(2099, 1, 1, tzinfo=UTC),
            symbols=[self.symbol],
            timeframes=[self.timeframe],
            parameters=params,
            split=self.split if self.split in ("TRAIN", "VALIDATION", "OUT_OF_SAMPLE", "DEMO") else "TRAIN",
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
        price_value_per_lot: float | None = None,
        slippage: float = 0.0,
        intrabar_policy: IntrabarPolicy = "CONSERVATIVE_STOP_FIRST",
        volume: float = 0.01,
        max_concurrent: int = 1,
    ) -> None:
        self.strategy = strategy
        self.classifier = classifier or RegimeClassifier()
        self.spread_pips = spread_pips
        self.commission = commission_per_lot
        self.point = point
        self.loss_per_lot = loss_per_lot
        self.price_value_per_lot = price_value_per_lot
        self.slippage = slippage
        if intrabar_policy not in ("CONSERVATIVE_STOP_FIRST", "EXCLUDE_AMBIGUOUS"):
            raise ValueError("unknown intrabar policy")
        self.intrabar_policy = intrabar_policy
        self.volume = volume
        self.max_concurrent = max_concurrent
        self.cost_model = CostModel(
            spread=CostCategory.MODELED,
            slippage=CostCategory.MODELED if slippage > 0 else CostCategory.ZERO,
            commission=CostCategory.MODELED if commission_per_lot > 0 else CostCategory.ZERO,
            swap=CostCategory.ZERO,
            label=f"backtest(spread={spread_pips}pips)",
        )

    def run(
        self,
        bars: list[Bar],
        symbol: str = "UNKNOWN",
        timeframe: Timeframe = Timeframe.H1,
        split: SplitName = "TRAIN",
        trade_start: datetime | None = None,
    ) -> BacktestResult:
        """Execute le backtest bar par bar. Strictement chronologique."""
        result = BacktestResult(
            symbol=symbol,
            timeframe=timeframe.value,
            strategy_id=self.strategy.id,
            strategy_version=self.strategy.version,
            split=split,
            intrabar_policy=self.intrabar_policy,
        )

        if len(bars) < MIN_BARS_FOR_EVAL + 1:
            log.warning("Not enough bars for backtest: %d < %d", len(bars), MIN_BARS_FOR_EVAL)
            return result

        result.period_start = bars[0].time
        result.period_end = bars[-1].time

        if any(a.time >= b.time for a, b in zip(bars[:-1], bars[1:], strict=True)):
            raise ValueError("bars must be strictly chronological without duplicates")
        open_positions: list[VirtualPosition] = []
        pending: tuple[StrategySignal, MarketRegime] | None = None
        spread = self.spread_pips * self.point

        for i in range(MIN_BARS_FOR_EVAL, len(bars)):
            result.bars_processed += 1

            current_bar = bars[i]
            # Signal decide a la cloture i-1; execution au premier prix de i.
            if pending is not None:
                pending_signal, regime = pending
                pending = None
                fill = current_bar.open + spread if pending_signal.side == Side.BUY else current_bar.open
                direction = 1 if pending_signal.side == Side.BUY else -1
                valid_stop = (fill - pending_signal.stop_loss) * direction > 0
                valid_tp = pending_signal.take_profit is None or (pending_signal.take_profit - fill) * direction > 0
                if valid_stop and valid_tp and len(open_positions) < self.max_concurrent:
                    trade_key = (
                        f"{self.strategy.id}|{self.strategy.version}|{symbol}|{timeframe.value}|{split}|"
                        f"{i}|{current_bar.time.isoformat()}|{pending_signal.side.value}|{fill}|"
                        f"{pending_signal.stop_loss}|{pending_signal.take_profit}"
                    )
                    open_positions.append(VirtualPosition(
                        trade_id=f"BT-{uuid5(NAMESPACE_URL, trade_key).hex[:12]}", symbol=symbol,
                        side=pending_signal.side, entry=fill, stop_loss=pending_signal.stop_loss,
                        take_profit=pending_signal.take_profit, opened_at=current_bar.time,
                        bar_index=i, confidence=pending_signal.confidence,
                        reason=pending_signal.reason, regime=regime,
                        initial_risk=self._initial_risk(fill, pending_signal.stop_loss),
                    ))
                else:
                    result.rejected_signals += 1

            # 1. Update open positions avec la barre courante
            newly_closed: list[tuple[VirtualPosition, int]] = []
            for pos in list(open_positions):
                exit_price = self._check_exit(pos, current_bar)
                if exit_price is not None:
                    # Le chemin intrabar est inconnu: ne jamais crediter le high/low
                    # apres une sortie. Seul le prix de liquidation est certain.
                    self._update_mfe_mae(pos, current_bar, exit_price)
                    pos.exit_price = exit_price
                    pos.closed_at = current_bar.time
                    bars_held = i - pos.bar_index
                    newly_closed.append((pos, bars_held))
                elif pos.exit_reason == "AMBIGUOUS":
                    result.ambiguous_positions.append(pos)
                    open_positions.remove(pos)
                else:
                    self._update_mfe_mae(pos, current_bar)

            for pos, bars_held in newly_closed:
                open_positions.remove(pos)
                trade = self._finalize_trade(pos, bars_held, spread)
                result.trades.append(trade)

            # Decision apres la cloture i; aucune lecture de la barre i+1.
            if i < len(bars) - 1 and (trade_start is None or current_bar.time >= trade_start) and len(open_positions) < self.max_concurrent:
                visible_bars = bars[:i + 1]
                signal = self._evaluate_strategy(visible_bars, symbol, timeframe)
                if signal is not None:
                    pending = (signal, self.classifier.classify(visible_bars).regime)
                else:
                    result.rejected_signals += 1

        # Close remaining positions at last bar
        if open_positions:
            last_bar = bars[-1]
            for pos in open_positions:
                exit_p = last_bar.close if pos.side == Side.BUY else last_bar.close + spread
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
        """Chaque split utilise le passe comme warmup, sans trader avant son debut."""
        segments = split_bars(all_bars, config)
        results: dict[SplitName, BacktestResult] = {}
        for split_name, split_bars_list in segments.items():
            if not split_bars_list:
                results[split_name] = BacktestResult(split=split_name,
                                                     intrabar_policy=self.intrabar_policy)
                continue
            prefix = [bar for bar in all_bars if bar.time <= split_bars_list[-1].time]
            results[split_name] = self.run(prefix, symbol, timeframe, split_name,
                                           trade_start=split_bars_list[0].time)
            results[split_name].period_start = split_bars_list[0].time
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
        decision_time = last_bar.close_time or last_bar.time + timedelta(minutes=timeframe.minutes)
        decision_time = decision_time if decision_time.tzinfo else decision_time.replace(tzinfo=UTC)
        tick = Tick(
            symbol=symbol,
            time=decision_time,
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
            now=decision_time,
            candidate=cand,
        )
        return self.strategy.evaluate(ctx)

    def _update_mfe_mae(self, pos: VirtualPosition, bar: Bar, exit_price: float | None = None) -> None:
        """Met a jour MFE/MAE en prix."""
        if pos.side == Side.BUY:
            favorable = exit_price if exit_price is not None else bar.high
            adverse = exit_price if exit_price is not None else bar.low
            if pos.mfe_price is None or favorable > pos.mfe_price:
                pos.mfe_price = favorable
            if pos.mae_price is None or adverse < pos.mae_price:
                pos.mae_price = adverse
        else:
            spread = self.spread_pips * self.point
            favorable = exit_price if exit_price is not None else bar.low + spread
            adverse = exit_price if exit_price is not None else bar.high + spread
            if pos.mfe_price is None or favorable < pos.mfe_price:
                pos.mfe_price = favorable
            if pos.mae_price is None or adverse > pos.mae_price:
                pos.mae_price = adverse

    def _check_exit(self, pos: VirtualPosition, bar: Bar) -> float | None:
        """Verifie si SL ou TP touche sur la barre courante. Retourne exit_price ou None."""
        spread = self.spread_pips * self.point
        opening_liquidation = bar.open if pos.side == Side.BUY else bar.open + spread
        if pos.side == Side.BUY:
            if opening_liquidation <= pos.stop_loss:
                pos.exit_reason = "SL_GAP"
                return opening_liquidation
            if pos.take_profit is not None and opening_liquidation >= pos.take_profit:
                pos.exit_reason = "TP_GAP"
                return pos.take_profit
            if bar.low <= pos.stop_loss:
                both = pos.take_profit is not None and bar.high >= pos.take_profit
                if both and self.intrabar_policy == "EXCLUDE_AMBIGUOUS":
                    pos.exit_reason = "AMBIGUOUS"
                    return None
                pos.exit_reason = ("AMBIGUOUS_STOP_FIRST" if pos.take_profit is not None
                                   and bar.high >= pos.take_profit else "SL")
                return pos.stop_loss
            if pos.take_profit is not None and bar.high >= pos.take_profit:
                pos.exit_reason = "TP"
                return pos.take_profit
        else:  # SELL
            if opening_liquidation >= pos.stop_loss:
                pos.exit_reason = "SL_GAP"
                return opening_liquidation
            if pos.take_profit is not None and opening_liquidation <= pos.take_profit:
                pos.exit_reason = "TP_GAP"
                return pos.take_profit
            if bar.high + spread >= pos.stop_loss:
                both = pos.take_profit is not None and bar.low + spread <= pos.take_profit
                if both and self.intrabar_policy == "EXCLUDE_AMBIGUOUS":
                    pos.exit_reason = "AMBIGUOUS"
                    return None
                pos.exit_reason = ("AMBIGUOUS_STOP_FIRST" if pos.take_profit is not None
                                   and bar.low + spread <= pos.take_profit else "SL")
                return pos.stop_loss
            if pos.take_profit is not None and bar.low + spread <= pos.take_profit:
                pos.exit_reason = "TP"
                return pos.take_profit
        return None

    def _initial_risk(self, entry: float, stop_loss: float) -> float:
        distance = abs(entry - stop_loss)
        value_per_lot = (self.price_value_per_lot if self.price_value_per_lot is not None
                         else self.loss_per_lot / distance)
        return (distance * value_per_lot * self.volume
                + abs(self.commission * self.volume)
                + abs(self.slippage) * value_per_lot * self.volume)

    def _finalize_trade(self, pos: VirtualPosition, bars_held: int, spread: float) -> BacktestTrade:
        """Finalise un trade et calcule les R metrics + fill record."""
        assert pos.exit_price is not None
        assert pos.closed_at is not None

        side_sign = 1 if pos.side == Side.BUY else -1

        r_metrics = compute_r(
            side_sign=side_sign,
            entry=pos.entry,
            stop_loss=pos.stop_loss,
            exit_price=pos.exit_price,
            take_profit=pos.take_profit,
            mfe_price=pos.mfe_price,
            mae_price=pos.mae_price,
            opened_at=pos.opened_at,
            closed_at=pos.closed_at,
            spread_at_entry=spread,
            slippage=self.slippage,
            commission=self.commission * self.volume,
            estimated_commission=self.commission * self.volume,
            estimated_slippage=self.slippage,
            initial_risk=pos.initial_risk,
            swap=0.0,
            loss_per_lot=self.loss_per_lot if self.price_value_per_lot is None else None,
            price_value_per_lot=self.price_value_per_lot,
            volume=self.volume,
        )

        # FillRecord: monetary economics derived from same price conversion
        sl_distance = abs(pos.entry - pos.stop_loss)
        value_per_lot = (self.price_value_per_lot if self.price_value_per_lot is not None
                         else self.loss_per_lot / sl_distance if sl_distance > 0 else 1.0)
        price_value = value_per_lot * self.volume
        pnl_price = (pos.exit_price - pos.entry) * side_sign
        gross_pnl = pnl_price * price_value
        slippage_cost = abs(self.slippage) * price_value
        commission_cost = abs(self.commission * self.volume)
        net_pnl = gross_pnl - slippage_cost - commission_cost

        fill = FillRecord(
            symbol=pos.symbol,
            side=side_sign,
            trade_id=pos.trade_id,
            entry_price=pos.entry,
            exit_price=pos.exit_price,
            stop_loss=pos.stop_loss,
            take_profit=pos.take_profit,
            opened_at=pos.opened_at,
            closed_at=pos.closed_at,
            exit_reason=pos.exit_reason,
            volume=self.volume,
            spread_cost=spread * price_value,
            slippage_cost=slippage_cost,
            commission=commission_cost,
            swap=0.0,
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            initial_risk=r_metrics.initial_risk,
            r_multiple=r_metrics.realized_r,
            cost_model=self.cost_model,
        )

        return BacktestTrade(
            position=pos,
            r_metrics=r_metrics,
            fill=fill,
            bars_held=bars_held,
        )
