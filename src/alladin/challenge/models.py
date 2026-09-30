"""ChallengeProfile : règles officielles FTMO vs règles expérimentales ALLADIN (toutes configurables)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from alladin.core.enums import AssetCategory, RuleSource, RunState


class DailyLossReference(StrEnum):
    # FTMO : référence = solde (ou equity si supérieure) au début de la journée
    MAX_BALANCE_EQUITY = "max_balance_equity"
    START_EQUITY = "start_equity"
    START_BALANCE = "start_balance"


class PhaseSpec(BaseModel):
    name: str
    profit_target_pct: float = Field(gt=0)


class OfficialRules(BaseModel):
    """Règles du programme FTMO (modifiables pour suivre une évolution du programme)."""

    daily_loss_pct: float = Field(default=5.0, gt=0)  # % du solde de départ de la phase
    max_total_loss_pct: float = Field(default=10.0, gt=0)  # perte statique sur le solde de départ
    min_trading_days: int = Field(default=4, ge=0)
    daily_loss_reference: DailyLossReference = DailyLossReference.MAX_BALANCE_EQUITY
    reset_timezone: str = "Europe/Prague"  # minuit CE(S)T
    reset_hour: int = Field(default=0, ge=0, le=23)
    target_measured_on: Literal["balance", "equity"] = "balance"


class ConsistencyRule(BaseModel):
    enabled: bool = False
    max_best_day_share_pct: float = Field(default=50.0, gt=0, le=100)  # best_day / total_profit


class ExtraRules(BaseModel):
    """Règles expérimentales ALLADIN, NON officielles FTMO."""

    max_days_per_phase: int | None = 14
    soft_daily_loss_pct: float | None = 3.0  # bloque les nouveaux trades du jour (pas éliminatoire)
    consistency: ConsistencyRule = ConsistencyRule()
    require_flat_to_pass: bool = True
    close_positions_on_fail: bool = False


class RiskRules(BaseModel):
    """Règles du RiskEngine ALLADIN (enveloppe de travail, plafonds, exposition)."""

    working_capital_pct: float = Field(default=10.0, gt=0, le=100)  # % de l'equity
    max_trade_risk_pct_of_working_capital: float = Field(default=8.0, gt=0, le=100)  # plafond, pas défaut
    over_cap_policy: Literal["reject", "clip"] = "reject"
    max_open_positions: int = Field(default=5, ge=1)
    max_total_open_risk_pct_of_wc: float = Field(default=30.0, gt=0)
    max_currency_net_risk_pct_of_wc: float = Field(default=15.0, gt=0)
    max_correlation: float = Field(default=0.85, gt=0, le=1)
    max_spread_to_sl_ratio: float = Field(default=0.25, gt=0)
    max_spread_points: float | None = None
    max_entry_deviation_to_sl_ratio: float = Field(default=0.15, gt=0)
    min_risk_reward: float = Field(default=0.0, ge=0)
    max_margin_usage_pct: float = Field(default=50.0, gt=0, le=100)  # % de la marge libre
    headroom_buffer_pct_of_baseline: float = Field(default=0.25, ge=0)
    allow_hedging: bool = False  # interdit BUY+SELL simultanés sur le même instrument


class UniverseRules(BaseModel):
    allowed_categories: list[AssetCategory] = [
        AssetCategory.FOREX_MAJOR,
        AssetCategory.FOREX_MINOR,
        AssetCategory.FOREX_JPY,
    ]
    include_symbols: list[str] = []
    exclude_symbols: list[str] = []
    max_spread_atr_ratio: float = 0.15
    shortlist_size: int = 10


class ChallengeProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str = ""
    initial_balance: float = Field(gt=0)
    phases: list[PhaseSpec] = Field(min_length=1)
    official_rules: OfficialRules = OfficialRules()
    extra_rules: ExtraRules = ExtraRules()
    risk: RiskRules = RiskRules()
    universe: UniverseRules = UniverseRules()

    @model_validator(mode="after")
    def _check(self) -> ChallengeProfile:
        from zoneinfo import ZoneInfo

        ZoneInfo(self.official_rules.reset_timezone)  # lève si invalide
        return self


class RuleViolation(BaseModel):
    rule: str
    source: RuleSource
    message: str
    observed: float | None = None
    limit: float | None = None
    fatal: bool = True  # True => run FAILED ; False => blocage des nouveaux ordres
    at: datetime


class WatchdogEvent(BaseModel):
    type: str
    detail: dict[str, Any] = {}


class PhaseResult(BaseModel):
    phase: int
    name: str
    started_at: datetime
    passed_at: datetime
    baseline_balance: float
    final_balance: float
    profit_pct: float
    trading_days: int


class WatchdogState(BaseModel):
    """État persistable du watchdog (restaurable après redémarrage)."""

    run_id: str
    run_state: RunState = RunState.CREATED
    phase_index: int = 0
    baseline_balance: float
    phase_started_at: datetime | None = None
    day_key: str | None = None
    day_start_balance: float = 0.0
    day_start_equity: float = 0.0
    trading_days: list[str] = []
    daily_closed_pnl: dict[str, float] = {}
    peak_equity: float = 0.0
    lowest_equity: float = 0.0
    last_balance: float = 0.0
    last_equity: float = 0.0
    blocked_day: str | None = None  # jour (clé) jusqu'auquel les nouveaux ordres sont bloqués
    violations: list[RuleViolation] = []
    phase_results: list[PhaseResult] = []
    close_positions_requested: bool = False


class WatchdogReport(BaseModel):
    run_id: str
    run_state: RunState
    phase_number: int
    phase_name: str
    baseline_balance: float
    balance: float
    equity: float
    floating_pnl: float
    target_pct: float
    target_level: float
    profit_pct: float  # (mesure - baseline) / baseline * 100, selon target_measured_on
    daily_floor: float
    daily_headroom: float
    daily_loss_used_pct: float  # % de la limite journalière consommée
    total_floor: float
    total_headroom: float
    total_loss_used_pct: float
    trading_days: int
    min_trading_days: int
    best_day_profit: float
    best_day_share_pct: float | None
    days_elapsed: float
    max_days: int | None
    can_open_new_positions: bool
    blocked_reasons: list[str] = []
    violations: list[RuleViolation] = []
    events: list[WatchdogEvent] = []
    close_positions_requested: bool = False
