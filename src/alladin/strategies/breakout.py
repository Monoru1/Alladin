"""BREAKOUT-01 : cassure du canal 20 barres avec expansion de volatilité."""

from __future__ import annotations

from typing import ClassVar

from alladin.core.enums import MarketRegime, Side
from alladin.strategies.base import Strategy, StrategyContext, StrategySignal


class Breakout01(Strategy):
    id = "BREAKOUT-01"
    version = "1.0.0"
    compatible_regimes: ClassVar[frozenset[MarketRegime]] = frozenset({MarketRegime.BREAKOUT})
    description = (
        "Suit une cassure du canal de Donchian 20 confirmée par une barre d'expansion (TR >= 1,3 ATR)."
    )

    def evaluate(self, ctx: StrategyContext) -> StrategySignal | None:
        c = ctx.candidate
        m, tick = c.metrics, c.tick
        if not m or tick is None:
            return None
        up = m["close"] > m["donchian_high"]
        down = m["close"] < m["donchian_low"]
        if not (up or down):
            return None
        if m["tr_last_atr"] > float(self.params.get("max_tr_atr", 3.5)):
            return None  # mouvement déjà épuisé
        side = Side.BUY if up else Side.SELL
        d = 1 if up else -1
        atr = m["atr"]
        entry = tick.ask if side is Side.BUY else tick.bid
        sl_mult = float(self.params.get("sl_atr", 1.2))
        tp_mult = float(self.params.get("tp_atr", 2.4))
        return StrategySignal(
            side=side,
            entry=entry,
            stop_loss=entry - d * sl_mult * atr,
            take_profit=entry + d * tp_mult * atr,
            confidence=round(
                min(0.8, 0.45 + m["tr_last_atr"] / 8 + 0.1 * abs(c.tf_trend.get("H4", 0) + d) / 2), 2
            ),
            reason=f"cassure {'haussière' if up else 'baissière'} du canal 20 (TR={m['tr_last_atr']:.1f} ATR)",
        )
