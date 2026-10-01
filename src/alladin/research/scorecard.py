"""Strategy Scorecard : produit des metriques comparables par strategy/version/symbol/tf/regime/split.

Si l'echantillon est insuffisant : INSUFFICIENT_SAMPLE.
Aucun chiffre fictif.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from statistics import median

from alladin.research.backtest import BacktestResult, BacktestTrade

MINIMUM_TRADES = 30  # en-dessous : INSUFFICIENT_SAMPLE


@dataclass(frozen=True)
class ScorecardEntry:
    """Metriques pour une combinaison strategy/version/symbol/tf/regime/split."""

    strategy_id: str
    strategy_version: str
    symbol: str
    timeframe: str
    regime: str
    split: str

    # Sample
    sample_size: int
    trades: int
    wins: int
    losses: int
    insufficient: bool = False

    # R metrics
    win_rate: float | None = None
    expectancy_r: float | None = None
    median_r: float | None = None
    profit_factor: float | None = None
    max_drawdown_r: float | None = None
    avg_drawdown_r: float | None = None

    # MFE/MAE
    avg_mfe_r: float | None = None
    avg_mae_r: float | None = None

    # Timing
    avg_holding_time: timedelta | None = None
    median_holding_time: timedelta | None = None

    # Costs
    avg_spread_cost_r: float | None = None
    avg_commission_r: float | None = None
    total_r: float | None = None

    @property
    def status(self) -> str:
        return "INSUFFICIENT_SAMPLE" if self.insufficient else "OK"


def build_scorecard(
    result: BacktestResult,
    regime: str = "ALL",
) -> ScorecardEntry:
    """Construit un ScorecardEntry a partir d'un BacktestResult."""
    trades = result.trades
    n = len(trades)

    if n < MINIMUM_TRADES:
        return ScorecardEntry(
            strategy_id=result.strategy_id,
            strategy_version=result.strategy_version,
            symbol=result.symbol,
            timeframe=result.timeframe,
            regime=regime,
            split=result.split,
            sample_size=result.bars_processed,
            trades=n,
            wins=result.wins,
            losses=result.losses,
            insufficient=True,
        )

    rs = [t.r_metrics.realized_r for t in trades]
    mfes = [t.r_metrics.mfe_r for t in trades]
    maes = [t.r_metrics.mae_r for t in trades]
    hold_times = [t.r_metrics.holding_time for t in trades]
    spread_costs = [t.r_metrics.spread_cost_r for t in trades]
    comm_costs = [t.r_metrics.commission_r for t in trades]

    # Drawdown curve
    drawdowns: list[float] = []
    equity = 0.0
    peak = 0.0
    for r in rs:
        equity += r
        if equity > peak:
            peak = equity
        drawdowns.append(peak - equity)

    return ScorecardEntry(
        strategy_id=result.strategy_id,
        strategy_version=result.strategy_version,
        symbol=result.symbol,
        timeframe=result.timeframe,
        regime=regime,
        split=result.split,
        sample_size=result.bars_processed,
        trades=n,
        wins=result.wins,
        losses=result.losses,
        win_rate=result.win_rate,
        expectancy_r=result.expectancy_r,
        median_r=median(rs) if rs else None,
        profit_factor=result.profit_factor,
        max_drawdown_r=max(drawdowns) if drawdowns else 0.0,
        avg_drawdown_r=sum(drawdowns) / len(drawdowns) if drawdowns else 0.0,
        avg_mfe_r=sum(mfes) / n,
        avg_mae_r=sum(maes) / n,
        avg_holding_time=sum(hold_times, timedelta()) / n,
        median_holding_time=sorted(hold_times)[n // 2] if hold_times else None,
        avg_spread_cost_r=sum(spread_costs) / n,
        avg_commission_r=sum(comm_costs) / n,
        total_r=result.total_r,
    )


def build_scorecards_by_regime(
    result: BacktestResult,
) -> list[ScorecardEntry]:
    """Construit des scorecards separees par regime detecte."""
    # Group trades by regime
    by_regime: dict[str, list[BacktestTrade]] = {}
    for t in result.trades:
        regime = t.position.regime.value if t.position.regime else "UNKNOWN"
        by_regime.setdefault(regime, []).append(t)

    entries: list[ScorecardEntry] = []
    # Scorecard ALL
    entries.append(build_scorecard(result, regime="ALL"))

    # Per regime
    for regime_name, regime_trades in by_regime.items():
        sub_result = BacktestResult(
            trades=regime_trades,
            bars_processed=result.bars_processed,
            symbol=result.symbol,
            timeframe=result.timeframe,
            strategy_id=result.strategy_id,
            strategy_version=result.strategy_version,
            split=result.split,
            period_start=result.period_start,
            period_end=result.period_end,
        )
        entries.append(build_scorecard(sub_result, regime=regime_name))

    return entries
