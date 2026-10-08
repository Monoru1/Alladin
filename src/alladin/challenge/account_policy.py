"""Injected account/market constraints; no official rule or broker schedule inferred."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from alladin.core.enums import Side
from alladin.market.sessions import SessionRules


class PolicyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False, strict=True)

    @field_validator("*", mode="after")
    @classmethod
    def utc_times(cls, value: object) -> object:
        if isinstance(value, datetime):
            return value.astimezone(UTC)
        return value


class DrawdownRule(PolicyModel):
    mode: Literal["static", "trailing_balance", "trailing_equity", "trailing_eod"]
    loss_pct: float = Field(gt=0, le=100, strict=True)
    lock_floor_at_initial: bool = False


class AccountConstraints(PolicyModel):
    account_ref: str = Field(min_length=1)
    currency: str = Field(min_length=1)
    sessions: SessionRules | None = None
    permitted_actions: frozenset[str] = frozenset({"OPEN", "CLOSE", "PARTIAL_CLOSE", "MODIFY_STOP", "MODIFY_TARGET", "HOLD"})
    forbid_weekend_hold: bool = False
    max_market_break_seconds: int | None = Field(default=None, ge=0, strict=True)
    flatten_buffer_seconds: int = Field(default=300, ge=0, strict=True)
    drawdown: DrawdownRule | None = None
    max_aggregate_positions: int | None = Field(default=None, ge=0, strict=True)
    max_aggregate_risk: float | None = Field(default=None, ge=0, strict=True)
    max_group_risk: float | None = Field(default=None, ge=0, strict=True)
    forbid_opposite_accounts: bool = False
    managed_accounts: frozenset[str] = frozenset()

    @model_validator(mode="after")
    def valid_actions(self) -> AccountConstraints:
        known = {"OPEN", "CLOSE", "PARTIAL_CLOSE", "MODIFY_STOP", "MODIFY_TARGET", "HOLD"}
        if not self.permitted_actions <= known:
            raise ValueError("unknown permitted action")
        if any(not s.strip() or s != s.strip() for s in (self.account_ref, self.currency)):
            raise ValueError("unambiguous account/currency required")
        aggregate = any(x is not None for x in (self.max_aggregate_positions, self.max_aggregate_risk, self.max_group_risk)) or self.forbid_opposite_accounts
        if aggregate and self.account_ref not in self.managed_accounts:
            raise ValueError("aggregate rules require explicit managed account scope")
        return self


class AccountPolicyState(PolicyModel):
    account_ref: str
    currency: str
    observed_at: AwareDatetime
    valid_until: AwareDatetime
    initial_balance: float = Field(gt=0, strict=True)
    balance: float = Field(ge=0, strict=True)
    equity: float = Field(ge=0, strict=True)
    peak_balance: float = Field(ge=0, strict=True)
    peak_equity: float = Field(ge=0, strict=True)
    peak_eod_balance: float = Field(ge=0, strict=True)

    @model_validator(mode="after")
    def valid(self) -> AccountPolicyState:
        if self.valid_until < self.observed_at:
            raise ValueError("account state expiry before observation")
        if self.peak_balance < max(self.balance, self.initial_balance) or self.peak_equity < max(self.equity, self.initial_balance):
            raise ValueError("invalid high water marks")
        if not self.initial_balance <= self.peak_eod_balance <= self.peak_balance:
            raise ValueError("invalid end-of-day high water mark")
        return self

    def advance(self, *, balance: float, equity: float, observed_at: datetime,
                valid_until: datetime, end_of_day: bool = False) -> AccountPolicyState:
        if observed_at.utcoffset() is None or observed_at.astimezone(UTC) <= self.observed_at.astimezone(UTC):
            raise ValueError("state updates must progress causally")
        return AccountPolicyState(
            account_ref=self.account_ref, currency=self.currency, initial_balance=self.initial_balance,
            balance=balance, equity=equity, observed_at=observed_at, valid_until=valid_until,
            peak_balance=max(self.peak_balance, balance), peak_equity=max(self.peak_equity, equity),
            peak_eod_balance=max(self.peak_eod_balance, balance) if end_of_day else self.peak_eod_balance,
        )

    def floor(self, rule: DrawdownRule) -> float:
        reference = {"static": self.initial_balance, "trailing_balance": self.peak_balance,
                     "trailing_equity": self.peak_equity, "trailing_eod": self.peak_eod_balance}[rule.mode]
        floor = reference - self.initial_balance * rule.loss_pct / 100
        return min(floor, self.initial_balance) if rule.lock_floor_at_initial else floor


class MarketBreak(PolicyModel):
    symbol: str = Field(min_length=1)
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    weekend: bool

    @model_validator(mode="after")
    def ordered(self) -> MarketBreak:
        if self.ends_at.astimezone(UTC) <= self.starts_at.astimezone(UTC):
            raise ValueError("invalid market break")
        return self


class MarketSchedule(PolicyModel):
    observed_at: AwareDatetime
    valid_until: AwareDatetime
    source: str = Field(min_length=1)
    covered_symbols: frozenset[str] = Field(min_length=1)
    breaks: tuple[MarketBreak, ...] = ()

    @model_validator(mode="after")
    def valid(self) -> MarketSchedule:
        if self.valid_until.astimezone(UTC) < self.observed_at.astimezone(UTC):
            raise ValueError("invalid schedule freshness")
        if any(b.symbol not in self.covered_symbols for b in self.breaks):
            raise ValueError("break outside schedule coverage")
        return self

    def holding_deadline(self, constraints: AccountConstraints, symbol: str, now: datetime) -> MarketBreak | None:
        now = now.astimezone(UTC)
        for item in sorted(self.breaks, key=lambda b: b.starts_at.astimezone(UTC)):
            duration = (item.ends_at.astimezone(UTC)-item.starts_at.astimezone(UTC)).total_seconds()
            forbidden = (constraints.forbid_weekend_hold and item.weekend) or (
                constraints.max_market_break_seconds is not None and duration > constraints.max_market_break_seconds)
            if forbidden and item.starts_at.astimezone(UTC)-timedelta(seconds=constraints.flatten_buffer_seconds) <= now < item.ends_at.astimezone(UTC) and item.symbol.upper() == symbol.upper():
                return item
        return None


class ExposurePosition(PolicyModel):
    position_id: str = Field(min_length=1)
    account_ref: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    side: Side
    risk_amount: float = Field(ge=0, strict=True)
    group: str = Field(min_length=1)


class ExposureSnapshot(PolicyModel):
    observed_at: AwareDatetime
    valid_until: AwareDatetime
    currency: str = Field(min_length=1)
    account_refs: frozenset[str] = Field(min_length=1)
    positions: tuple[ExposurePosition, ...] = ()

    @model_validator(mode="after")
    def coherent(self) -> ExposureSnapshot:
        if self.valid_until < self.observed_at:
            raise ValueError("invalid exposure expiry")
        keys = [(p.account_ref, p.position_id) for p in self.positions]
        if len(set(keys)) != len(keys) or any(p.account_ref not in self.account_refs for p in self.positions):
            raise ValueError("duplicate or unscoped exposure")
        return self


def constraint_reason(
    constraints: AccountConstraints, *, action: str, now: datetime, symbol: str,
    state: AccountPolicyState | None, schedule: MarketSchedule | None,
    exposures: ExposureSnapshot | None, risk_amount: float | None, group: str | None, side: Side | None,
) -> str | None:
    """A refusal/review reason, not a sizing or execution permission."""
    now = now.astimezone(UTC)
    entry = action == "OPEN"
    if action not in constraints.permitted_actions:
        return "ACTION_NOT_PERMITTED"
    if entry and constraints.sessions is not None and not constraints.sessions.allows(now):
        return "TRADING_SESSION_CLOSED"
    if constraints.forbid_weekend_hold or constraints.max_market_break_seconds is not None:
        if (schedule is None or not schedule.observed_at <= now <= schedule.valid_until
                or symbol.upper() not in {s.upper() for s in schedule.covered_symbols}):
            return "MARKET_SCHEDULE_UNAVAILABLE"
        deadline = schedule.holding_deadline(constraints, symbol, now)
        if deadline:
            if now >= deadline.starts_at:
                return "MARKET_BREAK_ACTIVE"
            if action not in {"CLOSE"}:
                return "FLATTEN_BEFORE_MARKET_BREAK"
    if constraints.drawdown is not None:
        if state is None or not state.observed_at <= now <= state.valid_until:
            return "ACCOUNT_STATE_UNAVAILABLE"
        if state.account_ref != constraints.account_ref or state.currency != constraints.currency:
            return "ACCOUNT_STATE_MISMATCH"
        if state.equity <= state.floor(constraints.drawdown):
            if entry:
                return "DRAWDOWN_LIMIT"
            if action not in {"CLOSE", "PARTIAL_CLOSE", "MODIFY_STOP"}:
                return "DRAWDOWN_PROTECTION_REVIEW"
    aggregate = any(value is not None for value in (constraints.max_aggregate_positions,
                    constraints.max_aggregate_risk, constraints.max_group_risk)) or constraints.forbid_opposite_accounts
    if entry and aggregate:
        if (exposures is None or not exposures.observed_at <= now <= exposures.valid_until
                or exposures.account_refs != constraints.managed_accounts):
            return "EXPOSURE_UNAVAILABLE"
        if exposures.currency != constraints.currency:
            return "EXPOSURE_CURRENCY_MISMATCH"
        if constraints.max_aggregate_positions is not None and len(exposures.positions) >= constraints.max_aggregate_positions:
            return "AGGREGATE_POSITION_LIMIT"
        if constraints.max_aggregate_risk is not None or constraints.max_group_risk is not None:
            from math import isfinite

            if risk_amount is None or not isfinite(risk_amount) or risk_amount < 0 or group is None:
                return "PROPOSED_EXPOSURE_UNAVAILABLE"
            if constraints.max_aggregate_risk is not None and sum(p.risk_amount for p in exposures.positions)+risk_amount > constraints.max_aggregate_risk:
                return "AGGREGATE_RISK_LIMIT"
            if constraints.max_group_risk is not None and sum(p.risk_amount for p in exposures.positions if p.group == group)+risk_amount > constraints.max_group_risk:
                return "GROUP_RISK_LIMIT"
        if constraints.forbid_opposite_accounts:
            if side is None:
                return "PROPOSED_DIRECTION_UNAVAILABLE"
            if any(p.account_ref != constraints.account_ref and p.symbol.upper() == symbol.upper() and p.side != side for p in exposures.positions):
                return "OPPOSITE_ACCOUNT_EXPOSURE"
    return None
