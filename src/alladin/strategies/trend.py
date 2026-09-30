"""TREND-01 : pullback vers l'EMA20 dans une tendance établie."""

from __future__ import annotations

from typing import ClassVar

from alladin.core.enums import MarketRegime, Side
from alladin.strategies.base import Strategy, StrategyContext, StrategySignal


class Trend01(Strategy):
    id = "TREND-01"
    version = "1.0.0"
    compatible_regimes: ClassVar[frozenset[MarketRegime]] = frozenset({MarketRegime.TREND})
    description = "Entrée sur repli vers l'EMA20 dans le sens de la tendance H1 (H4 non contraire)."

    def evaluate(self, ctx: StrategyContext) -> StrategySignal | None:
        c = ctx.candidate
        m, tick = c.metrics, c.tick
        if not m or tick is None:
            return None
        direction = 1 if m["ema20"] > m["ema50"] else -1
        h4 = c.tf_trend.get("H4", 0)
        if h4 == -direction:
            return None  # la timeframe supérieure contredit
        atr = m["atr"]
        pullback = (m["close"] - m["ema20"]) * direction / atr  # <0 : repli sous/sur l'EMA20
        rsi = m["rsi14"]
        if not (-0.8 <= pullback <= 0.6):
            return None
        if direction == 1 and not (38 <= rsi <= 68):
            return None
        if direction == -1 and not (32 <= rsi <= 62):
            return None
        side = Side.BUY if direction == 1 else Side.SELL
        entry = tick.ask if side is Side.BUY else tick.bid
        sl_mult = float(self.params.get("sl_atr", 1.5))
        tp_mult = float(self.params.get("tp_atr", 2.5))
        confidence = round(min(0.85, 0.5 + 0.4 * m["er20"] + (0.05 if h4 == direction else 0.0)), 2)
        return StrategySignal(
            side=side,
            entry=entry,
            stop_loss=entry - direction * sl_mult * atr,
            take_profit=entry + direction * tp_mult * atr,
            confidence=confidence,
            reason=f"tendance {'haussière' if direction == 1 else 'baissière'} (ER20={m['er20']:.2f}), repli {pullback:+.2f} ATR vs EMA20, RSI {rsi:.0f}",
        )
