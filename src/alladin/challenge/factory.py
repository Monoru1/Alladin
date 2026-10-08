"""Deterministic paired scenario campaigns; no broker, strategy or real capital.

Exogenous gross PnL paths are fixture inputs, not performance predictions.
Only simulated, flat, single-position episodes are supported. Rules are supplied.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from statistics import mean
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from alladin.challenge.account_policy import AccountConstraints, AccountPolicyState
from alladin.challenge.event_policy import CalendarSnapshot, EconomicEvent
from alladin.challenge.firm_policy import FirmProfile
from alladin.challenge.models import ChallengeProfile, WatchdogState
from alladin.challenge.policy_gate import GateVerdict, PolicyContext, ProposedAction, evaluate_action
from alladin.challenge.policy_serialization import canonical_json
from alladin.challenge.watchdog import ChallengeWatchdog
from alladin.core.enums import AccountType, RunState
from alladin.core.models import AccountSnapshot


class ScenarioStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    at: AwareDatetime
    gross_pnl_pct: float = Field(strict=True, ge=-50, le=50)
    cost_pct: float = Field(default=0.0, strict=True, ge=0, le=10)
    worst_equity_pct: float = Field(strict=True, ge=-60, le=0)
    calendar_available: bool = Field(default=True, strict=True)
    restricted_release: bool = Field(default=False, strict=True)
    restart: bool = Field(default=False, strict=True)
    peak_equity_pct: float | None = Field(default=None, strict=True, ge=0, le=100)
    end_of_day: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def path_valid(self) -> ScenarioStep:
        if self.peak_equity_pct is not None and self.peak_equity_pct < max(
            0.0, self.gross_pnl_pct - self.cost_pct
        ):
            raise ValueError("explicit peak must include net close gain")
        if self.worst_equity_pct > self.gross_pnl_pct - self.cost_pct:
            raise ValueError("intratrade trough must include net closing loss")
        return self


class ScenarioPath(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(min_length=1)
    steps: tuple[ScenarioStep, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def chronological(self) -> ScenarioPath:
        times = [s.at.astimezone(UTC) for s in self.steps]
        if any(b - a < timedelta(hours=2) for a, b in zip(times, times[1:], strict=False)):
            raise ValueError("episodes must progress at least two hours apart")
        return self


class CampaignVariant(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    id: str = Field(min_length=1)
    simulation_only: bool = Field(default=True, strict=True)
    challenge: ChallengeProfile
    firm: FirmProfile
    symbol: str
    reset_drawdown_on_phase: bool = Field(default=False, strict=True)
    hypothetical_evaluation_fee: float = Field(ge=0, strict=True)
    hypothetical_operating_cost: float = Field(default=0.0, ge=0, strict=True)
    hypothetical_reward_on_pass: float | None = Field(default=None, ge=0, strict=True)

    @model_validator(mode="after")
    def supported(self) -> CampaignVariant:
        json.dumps(self.challenge.model_dump(mode="json"), allow_nan=False)
        if (
            max(
                self.challenge.official_rules.daily_loss_pct, self.challenge.official_rules.max_total_loss_pct
            )
            > 100
        ):
            raise ValueError("loss rules above 100 percent unsupported in replay")
        if not self.simulation_only:
            raise ValueError("only simulated campaigns accepted")
        if not self.challenge.extra_rules.require_flat_to_pass:
            raise ValueError("campaigns require flat positions to validate a phase")
        constraints = self.firm.constraints
        if constraints is not None:
            template = AccountConstraints(
                account_ref=constraints.account_ref,
                currency=constraints.currency,
                drawdown=constraints.drawdown,
            )
            if constraints.drawdown is None or constraints.currency != "USD" or constraints != template:
                raise ValueError("only explicit USD drawdown constraints supported in campaigns")
        if (
            not self.firm.ea_allowed
            or self.firm.restrict_news is None
            or self.symbol not in self.firm.allowed_symbols
        ):
            raise ValueError("explicit synthetic symbol/EA/news rules required")
        return self


def _snapshot(balance: float, equity: float, at: datetime) -> AccountSnapshot:
    return AccountSnapshot(
        login_masked="SIMULATED",
        server="OFFLINE",
        currency="USD",
        balance=balance,
        equity=equity,
        margin=0.0,
        free_margin=equity,
        floating_pnl=equity - balance,
        account_type=AccountType.UNKNOWN,
        trade_allowed=False,
        timestamp=at,
    )


def replay_scenario(variant: CampaignVariant, path: ScenarioPath) -> dict[str, Any]:
    variant = CampaignVariant.model_validate(variant.model_dump(mode="python"))
    path = ScenarioPath.model_validate(path.model_dump(mode="python"))
    profile = variant.challenge
    initial = float(profile.initial_balance)
    balance = initial
    start = path.steps[0].at.astimezone(UTC) - timedelta(seconds=1)
    wd = ChallengeWatchdog.create(profile, f"SIM-{variant.id}-{path.id}", initial)
    wd.start(_snapshot(balance, balance, start), start)
    peak = initial
    drawdown = 0.0
    costs = 0.0
    decisions: list[dict[str, Any]] = []
    restores = 0
    constraints = variant.firm.constraints
    policy_failure = False
    account: AccountPolicyState | None = None
    if constraints is not None:
        account = AccountPolicyState(
            account_ref=constraints.account_ref,
            currency=constraints.currency,
            initial_balance=initial,
            balance=initial,
            equity=initial,
            peak_balance=initial,
            peak_equity=initial,
            peak_eod_balance=initial,
            observed_at=start,
            valid_until=start + timedelta(hours=2),
        )
    account_floors: list[dict[str, Any]] = []
    account_state_unavailable_reason: str | None = None
    for step in path.steps:
        if wd.run_state in {RunState.PASSED, RunState.FAILED, RunState.KILLED}:
            break
        at = step.at.astimezone(UTC)
        # Establish the new-day reference BEFORE observing the simulated loss.
        wd.update(_snapshot(balance, balance, at), at)
        if wd.state.run_state == RunState.FAILED:
            break
        if account is not None:
            account = account.advance(
                balance=balance, equity=balance, observed_at=at, valid_until=at + timedelta(hours=2)
            )
        if step.restart:
            wd = ChallengeWatchdog(profile, WatchdogState.model_validate_json(wd.state.model_dump_json()))
            if account is not None:
                account = AccountPolicyState.model_validate_json(account.model_dump_json())
            restores += 1
        cal = (
            CalendarSnapshot(
                at,
                at + timedelta(hours=1),
                "synthetic-campaign",
                (EconomicEvent("synthetic-release", at, frozenset({variant.symbol}), True),)
                if step.restricted_release
                else (),
            )
            if step.calendar_available
            else None
        )
        result = evaluate_action(
            ProposedAction.OPEN,
            PolicyContext(
                at, variant.symbol, 0, variant.firm, cal, variant.firm.restrict_news, account_state=account
            ),
        )
        if not wd.report(_snapshot(balance, balance, at), at).can_open_new_positions:
            decisions.append({"at": at.isoformat(), "verdict": "BLOCK", "reason": "WATCHDOG_BLOCKED"})
            continue
        decisions.append({"at": at.isoformat(), "verdict": result.verdict.value, "reason": result.reason})
        if result.verdict is not GateVerdict.ALLOW:
            continue
        base = wd.state.baseline_balance
        wd.record_trade_opened(at)
        if step.peak_equity_pct is not None:
            peak_time = at + timedelta(seconds=30)
            floating_peak = balance + base * step.peak_equity_pct / 100
            peak = max(peak, floating_peak)
            wd.update(_snapshot(balance, floating_peak, peak_time), peak_time, open_positions=1)
            if account is not None:
                account = account.advance(
                    balance=balance,
                    equity=floating_peak,
                    observed_at=peak_time,
                    valid_until=at + timedelta(hours=2),
                )
        trough = balance + base * step.worst_equity_pct / 100
        drawdown = max(drawdown, peak - trough)
        wd.update(
            _snapshot(balance, trough, at + timedelta(minutes=1)), at + timedelta(minutes=1), open_positions=1
        )
        # Stop a failed path at its observed trough; do not invent a later recovery/fill.
        if account is not None and constraints is not None and constraints.drawdown is not None:
            floor = account.floor(constraints.drawdown)
            if trough < 0:
                # Record observed insolvency without inventing a nonnegative account
                # state; AccountPolicyState deliberately cannot represent debt.
                account_state_unavailable_reason = "NEGATIVE_EQUITY"
            else:
                account = account.advance(
                    balance=balance,
                    equity=trough,
                    observed_at=at + timedelta(minutes=1),
                    valid_until=at + timedelta(hours=2),
                )
                floor = account.floor(constraints.drawdown)
            account_floors.append(
                {
                    "at": (at + timedelta(minutes=1)).isoformat(),
                    "mode": constraints.drawdown.mode,
                    "floor": floor,
                    "equity": trough,
                }
            )
            if trough <= floor:
                policy_failure = True
            if account_state_unavailable_reason is not None:
                account = None
        if wd.run_state is RunState.FAILED or policy_failure:
            break
        fee = base * step.cost_pct / 100
        costs += fee
        pnl = base * step.gross_pnl_pct / 100 - fee
        balance += pnl
        peak = max(peak, balance)
        drawdown = max(drawdown, peak - balance)
        close_at = at + timedelta(hours=1)
        wd.record_closed_pnl(pnl, close_at)
        phase_before = wd.phase_number
        wd.update(_snapshot(balance, balance, close_at), close_at, open_positions=0)
        if account is not None and constraints is not None and constraints.drawdown is not None:
            account = account.advance(
                balance=balance,
                equity=balance,
                observed_at=close_at,
                valid_until=at + timedelta(hours=2),
                end_of_day=step.end_of_day,
            )
            floor = account.floor(constraints.drawdown)
            account_floors.append(
                {
                    "at": close_at.isoformat(),
                    "mode": constraints.drawdown.mode,
                    "floor": floor,
                    "equity": balance,
                }
            )
            if balance <= floor:
                policy_failure = True
                break
            if wd.phase_number != phase_before and variant.reset_drawdown_on_phase:
                account = AccountPolicyState(
                    account_ref=constraints.account_ref,
                    currency=constraints.currency,
                    initial_balance=balance,
                    balance=balance,
                    equity=balance,
                    peak_balance=balance,
                    peak_equity=balance,
                    peak_eod_balance=balance,
                    observed_at=close_at,
                    valid_until=at + timedelta(hours=2),
                )
    report = wd.report(
        _snapshot(wd.state.last_balance, wd.state.last_equity, path.steps[-1].at), path.steps[-1].at
    )
    passed = wd.run_state is RunState.PASSED and not policy_failure
    reward = (
        (variant.hypothetical_reward_on_pass if passed else 0.0)
        if variant.hypothetical_reward_on_pass is not None
        else None
    )
    return {
        "variant": variant.id,
        "scenario": path.id,
        "status": "POLICY_FAILED" if policy_failure else wd.run_state.value,
        "passed": passed,
        "final_observed_balance": report.balance,
        "final_observed_equity": report.equity,
        "max_observed_drawdown": drawdown,
        "max_observed_drawdown_pct_initial": 100 * drawdown / initial,
        "charged_simulated_trade_costs": costs,
        "costs_complete": wd.run_state is not RunState.FAILED and not policy_failure,
        "account_drawdown_observations": account_floors,
        "drawdown_state": account.model_dump(mode="json") if account is not None else None,
        "drawdown_state_unavailable_reason": account_state_unavailable_reason,
        "hypothetical_evaluation_fee": variant.hypothetical_evaluation_fee,
        "hypothetical_operating_cost": variant.hypothetical_operating_cost,
        "hypothetical_reward": reward,
        "restores": restores,
        "failures": [v.rule for v in wd.state.violations if v.fatal]
        + (["policy_drawdown"] if policy_failure else []),
        "decisions": decisions,
    }


def build_campaign(variants: tuple[CampaignVariant, ...], paths: tuple[ScenarioPath, ...]) -> dict[str, Any]:
    if (
        not variants
        or not paths
        or len({v.id for v in variants}) != len(variants)
        or len({p.id for p in paths}) != len(paths)
    ):
        raise ValueError("unique nonempty variants and paths required")
    inputs = json.loads(canonical_json({"variants": variants, "paths": paths}))
    digest = hashlib.sha256(
        json.dumps(inputs, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()
    ).hexdigest()
    rows = [replay_scenario(v, p) for v in variants for p in paths]
    summaries = []
    for variant in variants:
        sample = [r for r in rows if r["variant"] == variant.id]
        summaries.append(
            {
                "variant": variant.id,
                "simulated_allocation": variant.challenge.initial_balance,
                "scenario_count": len(sample),
                "scenario_pass_fraction": sum(r["passed"] for r in sample) / len(sample),
                "state_counts": dict(sorted(Counter(r["status"] for r in sample).items())),
                "worst_observed_drawdown": max(r["max_observed_drawdown"] for r in sample),
                "mean_charged_simulated_trade_costs": mean(
                    r["charged_simulated_trade_costs"] for r in sample
                ),
                "mean_hypothetical_reward": mean(r["hypothetical_reward"] for r in sample)
                if variant.hypothetical_reward_on_pass is not None
                else None,
                "unfinished_scenarios": sum(
                    r["status"] not in {"PASSED", "FAILED", "KILLED", "POLICY_FAILED"} for r in sample
                ),
                "hypothetical_evaluation_fee_each": variant.hypothetical_evaluation_fee,
                "hypothetical_operating_cost_each": variant.hypothetical_operating_cost,
                "real_world_pass_probability": None,
                "real_cash_generated": None,
            }
        )
    return {
        "schema_version": 1,
        "scope": "SYNTHETIC_PAIRED_SCENARIO_REPLAY",
        "input_sha256": digest,
        "inputs": inputs,
        "summaries": summaries,
        "records": rows,
        "execution_authorized": False,
        "unattended_qualified": False,
        "limitations": [
            "No strategy returns, probability model, OOS edge or broker fills inferred",
            "Paths equally weighted by explicit scenario count; no real-world probability",
            "Static watchdog and explicitly supplied drawdown only; no overnight or aggregate exposure campaign support",
            "One flat episode at a time; no sizing, intrabar path or portfolio simulation",
            "Costs after a fatal intratrade trough are unknown, not assumed settled",
            "Rewards are explicit hypothetical inputs, never payouts or capital owned",
        ],
    }
