"""Classification heuristique du régime de marché (TREND/RANGE/BREAKOUT/...).

Heuristiques volontairement simples et transparentes ; chaque décision expose ses métriques.
Ordre de priorité : NEWS_EVENT > BREAKOUT > HIGH_VOLATILITY > REVERSAL_CONTEXT > TREND > RANGE > LOW_VOLATILITY.
"""

from __future__ import annotations

from pydantic import BaseModel

from alladin.core.enums import MarketRegime
from alladin.core.models import Bar
from alladin.market import indicators as ind
from alladin.market.context import MarketContext

MIN_BARS = 120


class RegimeAssessment(BaseModel):
    regime: MarketRegime
    confidence: float
    metrics: dict[str, float] = {}
    reasons: list[str] = []


def primary_metrics(bars: list[Bar]) -> dict[str, float] | None:
    """Métriques communes scanner/stratégies sur la timeframe principale."""
    if len(bars) < MIN_BARS:
        return None
    closes = [b.close for b in bars]
    atr_s = ind.atr_series(bars, 14)
    if not atr_s:
        return None
    a = atr_s[-1]
    if a <= 0:
        return None
    e20, e50 = ind.ema(closes, 20), ind.ema(closes, 50)
    er = ind.efficiency_ratio(closes, 20)
    rsi14 = ind.rsi(closes, 14)
    don = ind.donchian(bars[:-1], 20)
    if None in (e20, e50, er, rsi14, don):
        return None
    assert e20 is not None and e50 is not None and er is not None and rsi14 is not None and don is not None
    last = bars[-1]
    tr_last = ind.true_ranges(bars[-2:])[-1]
    return {
        "atr": a,
        "atr_pct_rank": ind.percentile_rank(atr_s[-100:], a),
        "ema20": e20,
        "ema50": e50,
        "er20": er,
        "rsi14": rsi14,
        "close": last.close,
        "dist_ema50_atr": (last.close - e50) / a,
        "ema_spread_atr": (e20 - e50) / a,
        "donchian_high": don[0],
        "donchian_low": don[1],
        "tr_last_atr": tr_last / a,
        "momentum_atr": (closes[-1] - closes[-11]) / a,
    }


class RegimeClassifier:
    def classify(self, bars: list[Bar], context: MarketContext | None = None) -> RegimeAssessment:
        if context is not None and context.news_blackout:
            return RegimeAssessment(
                regime=MarketRegime.NEWS_EVENT,
                confidence=0.9,
                reasons=["événement macro à fort impact proche"],
            )
        m = primary_metrics(bars)
        if m is None:
            return RegimeAssessment(
                regime=MarketRegime.UNKNOWN, confidence=0.0, reasons=["données insuffisantes"]
            )

        broke_up = m["close"] > m["donchian_high"]
        broke_dn = m["close"] < m["donchian_low"]
        if (broke_up or broke_dn) and m["tr_last_atr"] >= 1.3:
            side = "haussière" if broke_up else "baissière"
            return RegimeAssessment(
                regime=MarketRegime.BREAKOUT,
                confidence=min(1.0, 0.5 + m["tr_last_atr"] / 6),
                metrics=m,
                reasons=[f"cassure {side} du canal 20 barres avec expansion (TR={m['tr_last_atr']:.1f} ATR)"],
            )
        if m["atr_pct_rank"] >= 0.92:
            return RegimeAssessment(
                regime=MarketRegime.HIGH_VOLATILITY,
                confidence=m["atr_pct_rank"],
                metrics=m,
                reasons=["ATR dans le top 8 % récent"],
            )
        # une tendance sans à-coup (ER élevé) n'est pas un contexte de retournement, même avec un RSI extrême
        if (m["rsi14"] >= 72 or m["rsi14"] <= 28) and abs(m["dist_ema50_atr"]) >= 2.0 and m["er20"] < 0.6:
            return RegimeAssessment(
                regime=MarketRegime.REVERSAL_CONTEXT,
                confidence=0.6,
                metrics=m,
                reasons=[
                    f"RSI extrême ({m['rsi14']:.0f}) et prix à {m['dist_ema50_atr']:+.1f} ATR de l'EMA50"
                ],
            )
        aligned = (m["ema20"] > m["ema50"] and m["close"] > m["ema50"]) or (
            m["ema20"] < m["ema50"] and m["close"] < m["ema50"]
        )
        if m["er20"] >= 0.35 and aligned and abs(m["ema_spread_atr"]) >= 0.3:
            return RegimeAssessment(
                regime=MarketRegime.TREND,
                confidence=min(1.0, m["er20"] + 0.2),
                metrics=m,
                reasons=[f"ER20={m['er20']:.2f}, EMA20/50 alignées"],
            )
        if m["atr_pct_rank"] <= 0.12:
            return RegimeAssessment(
                regime=MarketRegime.LOW_VOLATILITY,
                confidence=1 - m["atr_pct_rank"],
                metrics=m,
                reasons=["ATR dans le bas 12 % récent"],
            )
        if m["er20"] <= 0.25:
            return RegimeAssessment(
                regime=MarketRegime.RANGE,
                confidence=min(1.0, 0.9 - m["er20"]),
                metrics=m,
                reasons=[f"ER20={m['er20']:.2f} : mouvement peu directionnel"],
            )
        return RegimeAssessment(
            regime=MarketRegime.UNKNOWN, confidence=0.3, metrics=m, reasons=["signaux mixtes"]
        )
