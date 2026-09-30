"""Enveloppe de travail et dimensionnement de position (déterministe, sans LLM).

    working_capital = equity * working_capital_pct
    max_trade_risk  = working_capital * max_trade_risk_pct   (PLAFOND, pas un défaut)

Les valeurs tick MT5 (trade_tick_value) sont exprimées dans la devise du compte : aucune
conversion de devise n'est nécessaire tant qu'on s'appuie sur elles (voir docs/RISK_MODEL.md).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from alladin.core.models import InstrumentSpec


def working_capital(equity: float, working_capital_pct: float) -> float:
    return max(0.0, equity * working_capital_pct / 100)


def max_trade_risk(wc: float, max_trade_risk_pct_of_wc: float) -> float:
    return wc * max_trade_risk_pct_of_wc / 100


def loss_per_lot(spec: InstrumentSpec, entry: float, stop_loss: float) -> float:
    """Perte (devise du compte) pour 1 lot si le SL est touché."""
    if spec.trade_tick_size <= 0:
        return 0.0
    return abs(entry - stop_loss) / spec.trade_tick_size * spec.loss_tick_value


def floor_to_step(volume: float, step: float) -> float:
    if step <= 0:
        return 0.0
    d_step = Decimal(str(step))
    # round(…, 9) absorbe le bruit flottant (1.9999999999999 -> 2.0) sans jamais arrondir vers le haut de façon significative
    steps = (Decimal(str(round(volume, 9))) / d_step).to_integral_value(rounding=ROUND_DOWN)
    return float(steps * d_step)


@dataclass(frozen=True)
class SizingResult:
    volume: float
    raw_volume: float
    loss_per_lot: float
    actual_risk: float  # perte réelle au SL pour `volume`
    min_volume_risk: float  # risque encouru avec le volume minimum broker
    reason: str | None = None  # renseigné si volume == 0


class PositionSizer:
    def size(self, spec: InstrumentSpec, entry: float, stop_loss: float, risk_amount: float) -> SizingResult:
        lpl = loss_per_lot(spec, entry, stop_loss)
        if not math.isfinite(lpl) or lpl <= 0:
            return SizingResult(
                0.0, 0.0, 0.0, 0.0, 0.0, "perte par lot incalculable (tick size/value ou SL invalide)"
            )
        min_risk = lpl * spec.volume_min
        raw = risk_amount / lpl if risk_amount > 0 else 0.0
        volume = floor_to_step(min(raw, spec.volume_max), spec.volume_step)
        if volume < spec.volume_min:
            return SizingResult(
                0.0, raw, lpl, 0.0, min_risk, "risque autorisé inférieur au risque du volume minimum"
            )
        return SizingResult(volume, raw, lpl, volume * lpl, min_risk)
