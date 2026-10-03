"""Modèles du RiskEngine : contexte d'évaluation et décision."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from alladin.challenge.models import WatchdogReport
from alladin.core.approval import ApprovalToken
from alladin.core.models import AccountSnapshot, InstrumentSpec, Position, Tick
from alladin.risk.correlation import CorrelationMatrix


class RejectCode(StrEnum):
    POSITION_NOT_OWNED = "POSITION_NOT_OWNED"
    POSITION_ACTION_UNSUPPORTED = "POSITION_ACTION_UNSUPPORTED"
    MODE_SAFETY = "MODE_SAFETY"
    TRADING_MODE = "TRADING_MODE"
    LIVE_ACCOUNT = "LIVE_ACCOUNT"
    ACCOUNT_UNKNOWN = "ACCOUNT_UNKNOWN"
    KILL_SWITCH = "KILL_SWITCH"
    CHALLENGE_BLOCKED = "CHALLENGE_BLOCKED"
    TRADE_NOT_ALLOWED = "TRADE_NOT_ALLOWED"
    RUN_MISMATCH = "RUN_MISMATCH"
    EXPIRED = "EXPIRED"
    NO_STOP_LOSS = "NO_STOP_LOSS"
    INSTRUMENT_MISMATCH = "INSTRUMENT_MISMATCH"
    NOT_TRADABLE = "NOT_TRADABLE"
    ENTRY_TYPE_UNSUPPORTED = "ENTRY_TYPE_UNSUPPORTED"
    BAD_GEOMETRY = "BAD_GEOMETRY"
    STOPS_TOO_CLOSE = "STOPS_TOO_CLOSE"
    PRICE_MOVED = "PRICE_MOVED"
    SPREAD_TOO_WIDE = "SPREAD_TOO_WIDE"
    RISK_REWARD = "RISK_REWARD"
    RISK_EXCEEDS_CAP = "RISK_EXCEEDS_CAP"
    MAX_POSITIONS = "MAX_POSITIONS"
    HEDGING = "HEDGING"
    UNPROTECTED_POSITION = "UNPROTECTED_POSITION"
    EXPOSURE_UNKNOWN = "EXPOSURE_UNKNOWN"
    DAILY_HEADROOM = "DAILY_HEADROOM"
    TOTAL_HEADROOM = "TOTAL_HEADROOM"
    OPEN_RISK_CAP = "OPEN_RISK_CAP"
    CURRENCY_EXPOSURE = "CURRENCY_EXPOSURE"
    CORRELATION = "CORRELATION"
    SIZING = "SIZING"
    VOLUME_BELOW_MIN = "VOLUME_BELOW_MIN"
    MARGIN = "MARGIN"


class RiskReason(BaseModel):
    code: RejectCode
    message: str

    def __str__(self) -> str:
        return self.message


class RiskContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    now: datetime
    trading_mode: str = "demo"
    account: AccountSnapshot
    spec: InstrumentSpec
    tick: Tick
    positions: list[Position] = []  # positions ALLADIN ouvertes (ce run)
    specs: dict[str, InstrumentSpec] = {}  # specs des symboles des positions ouvertes
    watchdog: WatchdogReport
    kill_switch_active: bool = False
    margin_per_lot: float | None = None
    atr: float | None = None
    correlations: CorrelationMatrix | None = None


class RiskDecision(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    intent_id: str
    approved: bool
    reasons: list[RiskReason] = []  # motifs de rejet
    adjustments: list[str] = []  # réductions appliquées (approuvé mais réduit)
    working_capital: float = 0.0
    max_trade_risk: float = 0.0
    requested_risk_amount: float = 0.0
    risk_amount: float = 0.0  # risque réel au SL pour `volume`
    risk_pct_of_working_capital: float = 0.0
    risk_pct_of_equity: float = 0.0
    volume: float = 0.0
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    loss_per_lot: float = 0.0
    required_margin: float | None = None
    token: ApprovalToken | None = Field(default=None, exclude=True, repr=False)

    @property
    def status(self) -> str:
        return "APPROVED" if self.approved else "REJECTED"

    def reason_lines(self) -> list[str]:
        return [r.message for r in self.reasons]
