"""Vue portefeuille Spot canonique et contraintes deterministes Jafar."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from alladin.brokers.binance import BinanceAccount


class PortfolioError(ValueError):
    pass


class AssetHolding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    asset: str
    free: float = Field(ge=0, allow_inf_nan=False)
    locked: float = Field(ge=0, allow_inf_nan=False)
    mark_price: float = Field(gt=0, allow_inf_nan=False)
    value: float = Field(ge=0, allow_inf_nan=False)
    concentration_pct: float = Field(ge=0, le=100, allow_inf_nan=False)


class PortfolioSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    observed_at: datetime
    quote_asset: str
    cash_value: float = Field(ge=0, allow_inf_nan=False)
    invested_value: float = Field(ge=0, allow_inf_nan=False)
    total_value: float = Field(ge=0, allow_inf_nan=False)
    realized_pnl: float = Field(allow_inf_nan=False)
    unrealized_pnl: float | None = Field(default=None, allow_inf_nan=False)
    fees: float = Field(ge=0, allow_inf_nan=False)
    peak_value: float = Field(ge=0, allow_inf_nan=False)
    drawdown_pct: float = Field(ge=0, le=100, allow_inf_nan=False)
    holdings: tuple[AssetHolding, ...]
    exposure_by_asset: dict[str, float]
    exposure_by_group: dict[str, float]


class PortfolioLimits(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    max_invested_pct: float = Field(gt=0, le=100)
    max_asset_concentration_pct: float = Field(gt=0, le=100)
    max_group_concentration_pct: float = Field(gt=0, le=100)
    max_drawdown_pct: float = Field(gt=0, le=100)


class PortfolioRiskAssessment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    approved: bool
    reasons: tuple[str, ...]
    invested_pct: float = Field(ge=0, allow_inf_nan=False)
    remaining_investment_budget: float = Field(ge=0, allow_inf_nan=False)


class SpotPortfolioEngine:
    def __init__(
        self,
        quote_asset: str = "USDT",
        *,
        stablecoins: frozenset[str] | None = None,
        correlation_groups: Mapping[str, str] | None = None,
    ) -> None:
        if not quote_asset.strip():
            raise ValueError("quote asset required")
        self.quote_asset = quote_asset.upper()
        self.stablecoins = stablecoins or frozenset({self.quote_asset})
        if self.quote_asset not in self.stablecoins:
            raise ValueError("quote asset must be cash-like")
        self.correlation_groups = {
            asset.upper(): group for asset, group in (correlation_groups or {}).items()
        }

    def snapshot(
        self,
        account: BinanceAccount,
        marks: Mapping[str, float],
        *,
        peak_value: float | None = None,
        realized_pnl: float = 0.0,
        unrealized_pnl: float | None = None,
        fees: float = 0.0,
    ) -> PortfolioSnapshot:
        normalized_marks = {asset.upper(): value for asset, value in marks.items()}
        if not math.isfinite(realized_pnl) or (
            unrealized_pnl is not None and not math.isfinite(unrealized_pnl)
        ):
            raise PortfolioError("invalid PnL")
        if not math.isfinite(fees) or fees < 0:
            raise PortfolioError("invalid fees")
        raw: list[tuple[str, float, float, float, float]] = []
        for balance in account.balances:
            quantity = balance.total
            if quantity <= 0:
                continue
            asset = balance.asset.upper()
            if asset in self.stablecoins:
                mark = 1.0
            else:
                mark = normalized_marks.get(asset, 0.0)
                if not math.isfinite(mark) or mark <= 0:
                    raise PortfolioError(f"missing or invalid mark for {asset}")
            raw.append((asset, balance.free, balance.locked, mark, quantity * mark))
        total = sum(item[4] for item in raw)
        if total <= 0 or not math.isfinite(total):
            raise PortfolioError("portfolio has no measurable value")
        holdings = tuple(
            AssetHolding(
                asset=asset,
                free=free,
                locked=locked,
                mark_price=mark,
                value=value,
                concentration_pct=value / total * 100,
            )
            for asset, free, locked, mark, value in raw
        )
        exposure_by_asset = {
            item.asset: item.value for item in holdings if item.asset not in self.stablecoins
        }
        grouped: defaultdict[str, float] = defaultdict(float)
        for asset, value in exposure_by_asset.items():
            grouped[self.correlation_groups.get(asset, asset)] += value
        cash = sum(item.value for item in holdings if item.asset in self.stablecoins)
        peak = total if peak_value is None else peak_value
        if not math.isfinite(peak) or peak < total or peak <= 0:
            raise PortfolioError("peak value must be finite and not below current value")
        return PortfolioSnapshot(
            observed_at=account.observed_at.astimezone(UTC),
            quote_asset=self.quote_asset,
            cash_value=cash,
            invested_value=total - cash,
            total_value=total,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            fees=fees,
            peak_value=peak,
            drawdown_pct=(peak - total) / peak * 100,
            holdings=holdings,
            exposure_by_asset=exposure_by_asset,
            exposure_by_group=dict(grouped),
        )

    def assess(self, snapshot: PortfolioSnapshot, limits: PortfolioLimits) -> PortfolioRiskAssessment:
        total = snapshot.total_value
        invested_pct = snapshot.invested_value / total * 100
        reasons: list[str] = []
        if invested_pct > limits.max_invested_pct:
            reasons.append("MAX_INVESTED_EXCEEDED")
        if any(
            value / total * 100 > limits.max_asset_concentration_pct
            for value in snapshot.exposure_by_asset.values()
        ):
            reasons.append("ASSET_CONCENTRATION_EXCEEDED")
        if any(
            value / total * 100 > limits.max_group_concentration_pct
            for value in snapshot.exposure_by_group.values()
        ):
            reasons.append("CORRELATED_GROUP_EXCEEDED")
        if snapshot.drawdown_pct > limits.max_drawdown_pct:
            reasons.append("MAX_DRAWDOWN_EXCEEDED")
        budget = max(0.0, total * limits.max_invested_pct / 100 - snapshot.invested_value)
        return PortfolioRiskAssessment(
            approved=not reasons,
            reasons=tuple(reasons),
            invested_pct=invested_pct,
            remaining_investment_budget=budget,
        )
