"""CurrencyExposure / PortfolioExposure.

Mesure simplifiée : chaque position contribue son RISQUE AU SL (devise du compte), signé par
devise : BUY EURUSD => +R sur EUR, -R sur USD ; SELL => inverse. BUY EURUSD + BUY GBPUSD + SELL
USDCHF donnent donc trois fois le même biais "USD court". Une mesure en notionnel converti est
prévue (voir docs/RISK_MODEL.md).
"""

from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel

from alladin.core.enums import Side
from alladin.core.models import InstrumentSpec, Position
from alladin.risk.sizing import loss_per_lot


class PortfolioExposure(BaseModel):
    currency_net_risk: dict[str, float] = {}  # signé : >0 long la devise, <0 courte
    total_open_risk: float = 0.0
    risk_by_symbol: dict[str, float] = {}
    unprotected_tickets: list[int] = []  # positions sans SL (ne devrait jamais arriver)
    unknown_symbols: list[str] = []  # positions dont la spec est introuvable


def currency_legs(spec: InstrumentSpec, side: Side, risk: float) -> dict[str, float]:
    """Contribution signée par devise d'un trade de risque `risk`."""
    s = side.sign
    return {spec.currency_base: s * risk, spec.currency_profit: -s * risk}


def position_risk(pos: Position, spec: InstrumentSpec) -> float | None:
    if pos.sl is None or pos.sl <= 0:
        return None
    return loss_per_lot(spec, pos.price_open, pos.sl) * pos.volume


def compute_exposure(positions: list[Position], specs: dict[str, InstrumentSpec]) -> PortfolioExposure:
    net: dict[str, float] = defaultdict(float)
    by_symbol: dict[str, float] = defaultdict(float)
    unprotected: list[int] = []
    unknown: list[str] = []
    total = 0.0
    for pos in positions:
        spec = specs.get(pos.symbol)
        if spec is None:
            unknown.append(pos.symbol)
            continue
        risk = position_risk(pos, spec)
        if risk is None:
            unprotected.append(pos.ticket)
            continue
        total += risk
        by_symbol[pos.symbol] += risk
        for ccy, val in currency_legs(spec, pos.side, risk).items():
            net[ccy] += val
    return PortfolioExposure(
        currency_net_risk=dict(net),
        total_open_risk=total,
        risk_by_symbol=dict(by_symbol),
        unprotected_tickets=unprotected,
        unknown_symbols=sorted(set(unknown)),
    )
