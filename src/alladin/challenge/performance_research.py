"""Offline strategy performance evaluation on independently supplied closed trades.

Research-only: never promotes a strategy or authorizes broker execution.
Amounts are integer minor units, net P&L already includes fees and slippage.
Chronological train/test separation is mandatory to reduce lookahead risk.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite


@dataclass(frozen=True)
class ClosedTrade:
    trade_id: str
    closed_at: datetime
    net_pnl_minor: int

    def __post_init__(self) -> None:
        if not self.trade_id.strip() or type(self.net_pnl_minor) is not int:
            raise ValueError("trade identity and integer net P&L required")
        if self.closed_at.tzinfo is None or self.closed_at.utcoffset() is None:
            raise ValueError("aware close timestamp required")


@dataclass(frozen=True)
class PerformanceReport:
    trades: int
    total_net_minor: int
    win_rate: float | None
    profit_factor: float | None
    max_drawdown_minor: int
    max_drawdown_pct: float
    expectancy_minor: float | None


def evaluate_closed_trades(
    trades: tuple[ClosedTrade, ...], *, starting_equity_minor: int,
) -> PerformanceReport:
    if type(starting_equity_minor) is not int or starting_equity_minor <= 0:
        raise ValueError("positive starting equity required")
    ids: set[str] = set()
    previous: datetime | None = None
    equity = starting_equity_minor
    peak = equity
    worst_minor = 0
    worst_pct = 0.0
    wins = 0
    gains = 0
    losses = 0
    total = 0
    for trade in trades:
        stamp = trade.closed_at.astimezone(UTC)
        if trade.trade_id in ids or (previous is not None and stamp < previous):
            raise ValueError("duplicate or nonchronological trades")
        ids.add(trade.trade_id)
        previous = stamp
        pnl = trade.net_pnl_minor
        total += pnl
        wins += pnl > 0
        gains += max(0, pnl)
        losses += max(0, -pnl)
        equity += pnl
        drawdown = peak - equity
        if drawdown > worst_minor:
            worst_minor = drawdown
        if peak > 0:
            worst_pct = max(worst_pct, 100 * drawdown / peak)
        peak = max(peak, equity)
    return PerformanceReport(
        trades=len(trades), total_net_minor=total,
        win_rate=wins / len(trades) if trades else None,
        profit_factor=gains / losses if losses else (None if not gains else float("inf")),
        max_drawdown_minor=worst_minor, max_drawdown_pct=worst_pct,
        expectancy_minor=total / len(trades) if trades else None,
    )


@dataclass(frozen=True)
class HoldoutEvaluation:
    training: PerformanceReport
    holdout: PerformanceReport
    sufficient_evidence: bool
    warnings: tuple[str, ...]


def evaluate_holdout(
    *, training: tuple[ClosedTrade, ...], holdout: tuple[ClosedTrade, ...],
    starting_equity_minor: int, min_holdout_trades: int = 30,
) -> HoldoutEvaluation:
    if type(min_holdout_trades) is not int or min_holdout_trades < 1:
        raise ValueError("positive minimum holdout size required")
    if not training or not holdout:
        raise ValueError("both chronological partitions required")
    train_end = max(t.closed_at.astimezone(UTC) for t in training)
    test_start = min(t.closed_at.astimezone(UTC) for t in holdout)
    if train_end >= test_start:
        raise ValueError("training must end strictly before holdout starts")
    if {t.trade_id for t in training} & {t.trade_id for t in holdout}:
        raise ValueError("overlapping trade identifiers")
    train_report = evaluate_closed_trades(training, starting_equity_minor=starting_equity_minor)
    test_report = evaluate_closed_trades(holdout, starting_equity_minor=starting_equity_minor)
    warnings = []
    if len(holdout) < min_holdout_trades:
        warnings.append("INSUFFICIENT_HOLDOUT_SAMPLE")
    if test_report.total_net_minor <= 0:
        warnings.append("NONPOSITIVE_HOLDOUT_NET")
    if not isfinite(test_report.max_drawdown_pct):
        warnings.append("INVALID_DRAWDOWN")
    return HoldoutEvaluation(
        training=train_report, holdout=test_report,
        sufficient_evidence=not warnings, warnings=tuple(warnings),
    )
