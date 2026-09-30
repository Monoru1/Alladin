"""RANGE-01 : retour à la moyenne depuis les extrêmes d'un canal."""

from __future__ import annotations

from typing import ClassVar

from alladin.core.enums import MarketRegime, Side
from alladin.strategies.base import Strategy, StrategyContext, StrategySignal


class Range01(Strategy):
    id = "RANGE-01"
    version = "1.0.0"
    compatible_regimes: ClassVar[frozenset[MarketRegime]] = frozenset(
        {MarketRegime.RANGE, MarketRegime.LOW_VOLATILITY}
    )
    description = "Vend le haut / achète le bas du canal 20 barres, cible le milieu, SL au-delà de l'extrême."

    def evaluate(self, ctx: StrategyContext) -> StrategySignal | None:
        c = ctx.candidate
        m, tick = c.metrics, c.tick
        if not m or tick is None:
            return None
        hi, lo = m["donchian_high"], m["donchian_low"]
        width = hi - lo
        atr = m["atr"]
        if width < 2 * atr:
            return None  # canal trop étroit pour payer le spread
        pos = (m["close"] - lo) / width
        if pos >= 0.85:
            side = Side.SELL
        elif pos <= 0.15:
            side = Side.BUY
        else:
            return None
        entry = tick.ask if side is Side.BUY else tick.bid
        mid = (hi + lo) / 2
        sl = lo - 0.5 * atr if side is Side.BUY else hi + 0.5 * atr
        if abs(mid - entry) < 0.8 * abs(entry - sl):
            return None  # ratio gain/risque insuffisant
        return StrategySignal(
            side=side,
            entry=entry,
            stop_loss=sl,
            take_profit=mid,
            confidence=round(min(0.75, 0.45 + (1 - m["er20"]) * 0.3), 2),
            reason=f"prix à {pos:.0%} du canal 20 en régime {c.regime.value}, retour vers le milieu",
        )
