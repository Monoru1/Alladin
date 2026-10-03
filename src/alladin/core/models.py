"""Modèles métier partagés (broker, marché, ordres, TradeIntent)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from alladin.core.enums import (
    AccountType,
    AssetCategory,
    CloseReason,
    DealEntry,
    EntryType,
    MarketRegime,
    OrderAction,
    Side,
    SymbolTradeMode,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------- marché


class Tick(BaseModel):
    symbol: str
    time: datetime
    bid: float
    ask: float

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    @property
    def mid(self) -> float:
        return (self.ask + self.bid) / 2


class Bar(BaseModel):
    time: datetime
    close_time: datetime | None = None  # crypto: debut exclusif de la prochaine barre, UTC
    is_closed: bool | None = None
    open: float
    high: float
    low: float
    close: float
    tick_volume: float = 0
    spread: float = 0
    available_at: datetime | None = None  # quand la barre est devenue observable (reception)
    provenance: str | None = None  # source : "mt5:ICMarkets", "binance:public", etc.


class InstrumentSpec(BaseModel):
    """Spécification broker d'un instrument (les valeurs tick sont dans la devise du compte)."""

    symbol: str
    description: str = ""
    path: str = ""
    currency_base: str
    currency_profit: str
    currency_margin: str
    digits: int
    point: float
    trade_tick_size: float
    trade_tick_value: float
    trade_tick_value_loss: float = 0.0  # 0 => utiliser trade_tick_value
    trade_contract_size: float
    volume_min: float
    volume_max: float
    volume_step: float
    spread: float = 0.0  # en points
    trade_mode: SymbolTradeMode = SymbolTradeMode.FULL
    visible: bool = True
    stops_level: float = 0.0  # points
    freeze_level: float = 0.0  # points
    category: AssetCategory = AssetCategory.OTHER
    # True si le broker calcule la marge en mode « Forex » (actions/indices/futures => False) ; None = inconnu
    is_forex_like: bool | None = None

    @property
    def loss_tick_value(self) -> float:
        return self.trade_tick_value_loss if self.trade_tick_value_loss > 0 else self.trade_tick_value

    @property
    def is_tradable(self) -> bool:
        return self.trade_mode is SymbolTradeMode.FULL


# --------------------------------------------------------------------------- compte


class AccountSnapshot(BaseModel):
    login_masked: str
    server: str
    currency: str
    balance: float
    equity: float
    margin: float
    free_margin: float
    floating_pnl: float
    leverage: int = 0
    account_type: AccountType
    trade_allowed: bool = True
    timestamp: datetime = Field(default_factory=utcnow)


class Position(BaseModel):
    ticket: int
    symbol: str
    side: Side
    volume: float
    price_open: float
    sl: float | None = None
    tp: float | None = None
    price_current: float = 0.0
    profit: float = 0.0
    swap: float = 0.0
    commission: float = 0.0
    magic: int = 0
    comment: str = ""
    time_open: datetime = Field(default_factory=utcnow)


class PendingOrder(BaseModel):
    ticket: int
    symbol: str
    side: Side
    order_type: str
    volume: float
    price: float
    sl: float | None = None
    tp: float | None = None
    magic: int = 0
    comment: str = ""


class Deal(BaseModel):
    ticket: int
    order: int = 0
    position_id: int
    symbol: str
    side: Side | None = None
    entry: DealEntry
    volume: float
    price: float
    profit: float = 0.0
    commission: float = 0.0
    swap: float = 0.0
    fee: float = 0.0
    magic: int = 0
    comment: str = ""
    time: datetime
    close_reason: CloseReason = CloseReason.UNKNOWN

    @property
    def net(self) -> float:
        return self.profit + self.commission + self.swap + self.fee


# --------------------------------------------------------------------------- ordres


class OrderRequest(BaseModel):
    """Requête broker. Jamais construite par un agent : produite par ExecutionService."""

    action: OrderAction
    symbol: str
    side: Side
    volume: float
    entry_type: EntryType = EntryType.MARKET
    price: float | None = None  # prix demandé (référence pour le slippage)
    stop_loss: float | None = None
    take_profit: float | None = None
    deviation_points: int = 20
    magic: int = 0
    comment: str = ""
    position_ticket: int | None = None  # pour CLOSE


class OrderCheck(BaseModel):
    ok: bool
    retcode: int
    message: str = ""
    margin: float | None = None
    free_margin_after: float | None = None


class OrderResult(BaseModel):
    accepted: bool
    retcode: int
    retcode_name: str = ""
    message: str = ""
    order: int = 0
    deal: int = 0
    position_ticket: int = 0
    volume: float = 0.0
    requested_price: float | None = None
    executed_price: float | None = None
    bid: float | None = None
    ask: float | None = None
    spread_at_fill: float | None = None
    slippage: float | None = None  # > 0 = défavorable
    commission: float = 0.0
    executed_at: datetime = Field(default_factory=utcnow)


# --------------------------------------------------------------------------- TradeIntent


class TradeIntent(BaseModel):
    """Proposition d'un agent ou d'une stratégie. Aucune valeur n'est digne de confiance.

    Pas de champ `volume` : un agent ne choisit jamais le lot (extra="forbid").
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    intent_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    proposal_id: str | None = None
    opportunity_id: str | None = None
    cycle_id: str | None = None
    run_id: str
    agent: str
    instrument: str = Field(min_length=3, max_length=32)
    side: Side
    strategy_id: str
    strategy_version: str
    market_regime: MarketRegime = MarketRegime.UNKNOWN
    entry_type: EntryType = EntryType.MARKET
    entry: float | None = Field(default=None, allow_inf_nan=False, gt=0)
    stop_loss: float | None = Field(default=None, allow_inf_nan=False, gt=0)
    take_profit: float | None = Field(default=None, allow_inf_nan=False, gt=0)
    requested_risk_pct_of_working_capital: float = Field(allow_inf_nan=False, gt=0, le=100)
    confidence: float | None = Field(default=None, allow_inf_nan=False, ge=0, le=1)
    reason: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime
    sources: list[str] = Field(default_factory=list)

    @field_validator("created_at", "expires_at")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("datetime naïf refusé (UTC requis)")
        return v.astimezone(UTC)

    def model_post_init(self, _ctx: Any) -> None:
        if self.entry_type is not EntryType.MARKET and self.entry is None:
            raise ValueError("entry requis pour un ordre LIMIT/STOP")
