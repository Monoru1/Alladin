"""Explicit stop geometry for manual MT5 integration tests; never places orders."""
from __future__ import annotations

import math

from alladin.core.models import InstrumentSpec


def stop_distance_in_price(
    spec: InstrumentSpec, *, sl_pips: float, price_distance: float | None
) -> float:
    """CFDs require an explicit distance in price units, not a Forex pip approximation."""
    if price_distance is not None:
        if not math.isfinite(price_distance) or price_distance <= 0:
            raise ValueError("--sl-price-distance doit être strictement positif et fini")
        distance = price_distance
    else:
        if spec.is_forex_like is not True:
            raise ValueError(
                "Instrument non-Forex ou classification incertaine : "
                "utiliser --sl-price-distance (unités de prix), pas --sl-pips"
            )
        if not math.isfinite(sl_pips) or sl_pips <= 0:
            raise ValueError("--sl-pips doit être strictement positif et fini")
        distance = sl_pips * spec.point * 10
    if not math.isfinite(spec.point) or spec.point <= 0:
        raise ValueError("point broker invalide")
    if distance < spec.stops_level * spec.point:
        raise ValueError("distance SL inférieure au stops_level broker")
    if distance < spec.trade_tick_size or spec.trade_tick_size <= 0:
        raise ValueError("distance SL inférieure au tick ou tick_size invalide")
    return distance


def stop_prices(
    spec: InstrumentSpec, *, entry: float, direction: int, distance: float, rr: float
) -> tuple[float, float]:
    """Compute SL/TP, rejecting rounding that collapses protective stops."""
    if not all(math.isfinite(v) for v in (entry, distance, rr)):
        raise ValueError("prix/distance/RR non finis")
    if entry <= 0 or distance <= 0 or not 0 < rr <= 10 or direction not in (-1, 1):
        raise ValueError("paramètres SL/TP invalides")
    sl = round(entry - direction * distance, spec.digits)
    tp = round(entry + direction * distance * rr, spec.digits)
    if sl <= 0 or (entry - sl) * direction <= 0 or (tp - entry) * direction <= 0:
        raise ValueError("SL/TP invalides après arrondi")
    return sl, tp
