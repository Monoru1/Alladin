"""R Analytics : normalise chaque trade en unites de R.

1R = risque initial (distance entry -> SL en devise du compte).
Toute metrique est exprimee en R pour etre comparable entre symboles, tailles et devises.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class RMetrics:
    """Metriques R pour un trade unique."""

    initial_risk: float  # montant risque en devise (entry->SL * loss_per_lot * volume)
    planned_rr: float | None  # TP distance / SL distance (None si pas de TP)
    realized_r: float  # PnL / initial_risk (negatif = perte)
    mfe_r: float  # max favorable excursion en R
    mae_r: float  # max adverse excursion en R (positif = distance defavorable)
    holding_time: timedelta
    spread_cost_r: float  # spread paye a l'entree en R
    slippage_r: float  # slippage en R
    commission_r: float  # commission en R
    swap_r: float  # swap en R


def compute_r(
    *,
    side_sign: int,  # +1 BUY, -1 SELL
    entry: float,
    stop_loss: float,
    exit_price: float,
    take_profit: float | None = None,
    mfe_price: float | None = None,
    mae_price: float | None = None,
    opened_at: datetime,
    closed_at: datetime,
    spread_at_entry: float = 0.0,
    slippage: float = 0.0,
    commission: float = 0.0,
    swap: float = 0.0,
    loss_per_lot: float = 1.0,
    volume: float = 1.0,
) -> RMetrics:
    """Calcule les metriques R pour un trade.

    Toutes les distances sont calculees en prix brut puis normalisees par 1R.
    side_sign: +1 pour BUY, -1 pour SELL.
    """
    sl_distance = abs(entry - stop_loss)
    if sl_distance <= 0:
        raise ValueError("SL distance must be > 0")

    # 1R en devise du compte
    initial_risk = sl_distance * loss_per_lot * volume
    if initial_risk <= 0:
        raise ValueError("initial_risk must be > 0")

    # PnL brut en prix (sans costs)
    pnl_price = (exit_price - entry) * side_sign
    realized_pnl = pnl_price * loss_per_lot * volume + commission + swap

    realized_r = realized_pnl / initial_risk

    # Planned RR
    planned_rr: float | None = None
    if take_profit is not None:
        tp_distance = abs(take_profit - entry)
        planned_rr = tp_distance / sl_distance if sl_distance > 0 else None

    # MFE/MAE en R
    mfe_r = 0.0
    if mfe_price is not None:
        mfe_dist = (mfe_price - entry) * side_sign
        mfe_r = max(0.0, mfe_dist / sl_distance)

    mae_r = 0.0
    if mae_price is not None:
        mae_dist = (entry - mae_price) * side_sign  # adverse = opposite to side
        mae_r = max(0.0, mae_dist / sl_distance)

    # Costs en R
    spread_r = (spread_at_entry / sl_distance) if sl_distance > 0 else 0.0
    slip_r = (abs(slippage) / sl_distance) if sl_distance > 0 else 0.0
    comm_r = (abs(commission) / initial_risk) if initial_risk > 0 else 0.0
    swap_r = (swap / initial_risk) if initial_risk > 0 else 0.0

    return RMetrics(
        initial_risk=initial_risk,
        planned_rr=planned_rr,
        realized_r=round(realized_r, 4),
        mfe_r=round(mfe_r, 4),
        mae_r=round(mae_r, 4),
        holding_time=closed_at - opened_at,
        spread_cost_r=round(spread_r, 4),
        slippage_r=round(slip_r, 4),
        commission_r=round(comm_r, 4),
        swap_r=round(swap_r, 4),
    )
