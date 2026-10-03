"""R Analytics : normalise chaque trade en unites de R.

1R = risque initial (distance entry -> SL en devise du compte).
Toute metrique est exprimee en R pour etre comparable entre symboles, tailles et devises.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum


class CostCategory(StrEnum):
    """Source classification of a cost component."""

    OBSERVED = "OBSERVED"  # from actual market data (bid/ask spread)
    MODELED = "MODELED"  # configured parameter (fixed slippage, commission)
    ZERO = "ZERO"  # not modeled, assumed zero


@dataclass(frozen=True)
class CostModel:
    """Explicit cost convention for experimental comparison.

    Distinguishes observed costs (from market data), modeled costs
    (configured parameters), and absent costs (assumed zero).
    Two experiments are cost-comparable only if they share the same CostModel.
    """

    spread: CostCategory = CostCategory.MODELED
    slippage: CostCategory = CostCategory.ZERO
    commission: CostCategory = CostCategory.ZERO
    swap: CostCategory = CostCategory.ZERO
    label: str = ""
    maker_rate: float | None = None  # fraction of account-currency notional; negative = rebate
    taker_rate: float | None = None
    funding: CostCategory = CostCategory.ZERO
    fee_provenance: str = ""

    def __post_init__(self) -> None:
        for rate in (self.maker_rate, self.taker_rate):
            if rate is not None and (not math.isfinite(rate) or abs(rate) > 1):
                raise ValueError("fee rate must be finite and expressed as a fraction")
        if (self.maker_rate is not None or self.taker_rate is not None) and (
            self.commission is CostCategory.ZERO or not self.fee_provenance.strip()
        ):
            raise ValueError("maker/taker fees require classification and provenance")

    def fee(self, notional_account: float, liquidity: str) -> float:
        """One fill only. Account-currency conversion must precede this call."""
        if not math.isfinite(notional_account) or notional_account <= 0:
            raise ValueError("notional must be finite and positive")
        if liquidity not in ("MAKER", "TAKER"):
            raise ValueError("liquidity must be MAKER or TAKER")
        rate = self.maker_rate if liquidity == "MAKER" else self.taker_rate
        if rate is None:
            raise ValueError("maker/taker fee unknown; zero cannot be inferred")
        return notional_account * rate



@dataclass(frozen=True)
class FillRecord:
    """Common fill contract for the causal experimental bench.

    Captures the complete result of a simulated historical execution.
    All monetary values are in account currency. Immutable.

    For fair comparison, all experiments must produce FillRecords using
    the same CostModel and price-to-currency conversion conventions.
    """

    # Identity
    symbol: str
    side: int  # +1 BUY, -1 SELL
    trade_id: str
    # Prices
    entry_price: float
    exit_price: float
    stop_loss: float
    take_profit: float | None
    # Timing
    opened_at: datetime
    closed_at: datetime
    exit_reason: str
    # Position
    volume: float
    # Cost components (account currency)
    spread_cost: float  # diagnostic: spread already embedded in entry/exit prices
    slippage_cost: float
    commission: float
    swap: float
    # Economics (account currency)
    gross_pnl: float  # price movement * position value, before transaction costs
    net_pnl: float  # gross_pnl - slippage - commission + swap + funding_cashflow
    initial_risk: float  # monetary risk at protective stop
    r_multiple: float  # net_pnl / initial_risk
    # Cost transparency
    cost_model: CostModel
    # Optional provenance
    experiment_id: str = ""
    funding_cashflow: float = 0.0  # signed account-currency transfer; separate from swap


@dataclass(frozen=True)
class RMetrics:
    """Metriques R pour un trade unique."""

    initial_risk: float  # perte nette estimee au stop initial, figee apres ouverture
    planned_rr: float | None  # TP distance / SL distance (None si pas de TP)
    realized_r: float  # PnL / initial_risk (negatif = perte)
    mfe_r: float  # max favorable excursion en R
    mae_r: float  # max adverse excursion en R (positif = distance defavorable)
    holding_time: timedelta
    spread_cost_r: float  # spread paye a l'entree en R
    slippage_r: float  # slippage en R
    commission_r: float  # commission en R
    swap_r: float  # swap en R
    funding_r: float = 0.0  # signed cashflow, distinct from swap


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
    funding: float = 0.0,
    loss_per_lot: float | None = None,
    price_value_per_lot: float | None = None,
    estimated_commission: float = 0.0,
    estimated_slippage: float = 0.0,
    initial_risk: float | None = None,
    volume: float = 1.0,
) -> RMetrics:
    """Calcule les metriques R pour un trade.

    entry/exit/SL/TP/MFE/MAE sont des prix executables (ASK pour ouvrir
    LONG, BID pour liquider LONG; inversement pour SHORT). Le spread est
    donc deja dans ces prix; spread_at_entry n'est qu'un diagnostic.
    loss_per_lot, s'il est fourni, est la perte TOTALE pour un lot au SL,
    conformement a risk.sizing.loss_per_lot. price_value_per_lot est la
    valeur monetaire d'une unite de prix pour un lot.
    commission est un cout total aller-retour (signe indifferent).
    slippage est un deplacement adverse total en prix, applique une fois.
    side_sign: +1 pour BUY, -1 pour SELL.
    """
    sl_distance = (entry - stop_loss) * side_sign
    if side_sign not in (-1, 1) or sl_distance <= 0:
        raise ValueError("SL distance must be > 0")
    if price_value_per_lot is not None and loss_per_lot is not None:
        raise ValueError("choose price_value_per_lot or loss_per_lot")
    value_per_lot = price_value_per_lot if price_value_per_lot is not None else (
        loss_per_lot / sl_distance if loss_per_lot is not None else 1.0
    )
    if value_per_lot <= 0 or volume <= 0:
        raise ValueError("price value and volume must be positive")
    price_value = value_per_lot * volume
    risk = initial_risk if initial_risk is not None else (
        sl_distance * price_value + abs(estimated_commission)
        + abs(estimated_slippage) * price_value
    )
    if risk <= 0:
        raise ValueError("initial_risk must be > 0")

    # PnL brut en prix (sans costs)
    pnl_price = (exit_price - entry) * side_sign
    if not math.isfinite(funding):
        raise ValueError("funding cashflow must be finite")
    realized_pnl = (pnl_price - abs(slippage)) * price_value - abs(commission) + swap + funding

    realized_r = realized_pnl / risk

    # Planned RR
    planned_rr: float | None = None
    if take_profit is not None:
        tp_gain = (take_profit - entry) * side_sign * price_value
        planned_rr = (tp_gain - abs(estimated_commission)
                      - abs(estimated_slippage) * price_value) / risk

    # MFE/MAE en R
    mfe_r = 0.0
    if mfe_price is not None:
        mfe_dist = (mfe_price - entry) * side_sign
        mfe_r = max(0.0, mfe_dist * price_value / risk)

    mae_r = 0.0
    if mae_price is not None:
        mae_dist = (entry - mae_price) * side_sign  # adverse = opposite to side
        mae_r = max(0.0, mae_dist * price_value / risk)

    # Costs en R
    spread_r = spread_at_entry * price_value / risk
    slip_r = abs(slippage) * price_value / risk
    comm_r = abs(commission) / risk
    swap_r = swap / risk

    return RMetrics(
        initial_risk=risk,
        planned_rr=planned_rr,
        realized_r=round(realized_r, 4),
        mfe_r=round(mfe_r, 4),
        mae_r=round(mae_r, 4),
        holding_time=closed_at - opened_at,
        spread_cost_r=round(spread_r, 4),
        slippage_r=round(slip_r, 4),
        commission_r=round(comm_r, 4),
        swap_r=round(swap_r, 4),
        funding_r=round(funding / risk, 4),
    )


@dataclass(frozen=True)
class FundingSettlement:
    """Actual supplied settlement, never extrapolated from a constant interval.

    Positive rate means longs pay shorts. Notional is valued in account currency
    at this settlement; quantity changes require their actual settlement notional.
    """
    settlement_id: str
    settled_at: datetime
    rate: float
    notional_account: float
    provenance: str

    def __post_init__(self) -> None:
        if not self.settlement_id or not self.provenance.strip():
            raise ValueError("funding requires identity and provenance")
        if self.settled_at.tzinfo is None or self.settled_at.utcoffset() is None:
            raise ValueError("funding timestamp must be timezone aware")
        if not math.isfinite(self.rate) or abs(self.rate) > 1:
            raise ValueError("funding rate must be a finite fraction")
        if not math.isfinite(self.notional_account) or self.notional_account <= 0:
            raise ValueError("funding notional must be finite and positive")


def funding_cashflow(settlements: list[FundingSettlement], *, side_sign: int,
                     opened_at: datetime, closed_at: datetime, model: CostModel) -> float:
    """Bench convention: charge settlements in (open, close], no implicit schedule.

    Missing data must be handled by the caller as incomplete coverage. An empty
    list means no supplied settlements, never proof of zero funding.
    """
    if side_sign not in (-1, 1):
        raise ValueError("side must be +1 or -1")
    if any(t.tzinfo is None or t.utcoffset() is None for t in (opened_at, closed_at)):
        raise ValueError("funding interval must be timezone aware")
    if closed_at < opened_at:
        raise ValueError("funding interval reversed")
    if model.funding is CostCategory.ZERO:
        raise ValueError("funding not modeled; zero cannot be inferred")
    if len({s.settlement_id for s in settlements}) != len(settlements):
        raise ValueError("duplicate funding settlement")
    return sum(-side_sign * s.notional_account * s.rate for s in settlements
               if opened_at < s.settled_at <= closed_at)
