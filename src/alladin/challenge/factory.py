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

from alladin.challenge.event_policy import CalendarSnapshot, EconomicEvent
from alladin.challenge.firm_policy import FirmProfile
from alladin.challenge.models import ChallengeProfile, WatchdogState
from alladin.challenge.policy_gate import GateVerdict, PolicyContext, ProposedAction, evaluate_action
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

    @model_validator(mode="after")
    def path_valid(self) -> ScenarioStep:
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
        if self.firm.constraints is not None:
            raise ValueError(
                "campaign watchdog supports static drawdown only; account constraints require runtime replay"
            )
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
    for step in path.steps:
        if wd.run_state in {RunState.PASSED, RunState.FAILED, RunState.KILLED}:
            break
        at = step.at.astimezone(UTC)
        # Establish the new-day reference BEFORE observing the simulated loss.
        wd.update(_snapshot(balance, balance, at), at)
        if wd.state.run_state == RunState.FAILED:
            break
        if step.restart:
            wd = ChallengeWatchdog(profile, WatchdogState.model_validate_json(wd.state.model_dump_json()))
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
            PolicyContext(at, variant.symbol, 0, variant.firm, cal, variant.firm.restrict_news),
        )
        if not wd.report(_snapshot(balance, balance, at), at).can_open_new_positions:
            decisions.append({"at": at.isoformat(), "verdict": "BLOCK", "reason": "WATCHDOG_BLOCKED"})
            continue
        decisions.append({"at": at.isoformat(), "verdict": result.verdict.value, "reason": result.reason})
        if result.verdict is not GateVerdict.ALLOW:
            continue
        base = wd.state.baseline_balance
        wd.record_trade_opened(at)
        trough = balance + base * step.worst_equity_pct / 100
        drawdown = max(drawdown, peak - trough)
        wd.update(
            _snapshot(balance, trough, at + timedelta(minutes=1)), at + timedelta(minutes=1), open_positions=1
        )
        # Stop a failed path at its observed trough; do not invent a later recovery/fill.
        if wd.run_state is RunState.FAILED:
            break
        fee = base * step.cost_pct / 100
        costs += fee
        pnl = base * step.gross_pnl_pct / 100 - fee
        balance += pnl
        peak = max(peak, balance)
        drawdown = max(drawdown, peak - balance)
        close_at = at + timedelta(hours=1)
        wd.record_closed_pnl(pnl, close_at)
        wd.update(_snapshot(balance, balance, close_at), close_at, open_positions=0)
    report = wd.report(
        _snapshot(wd.state.last_balance, wd.state.last_equity, path.steps[-1].at), path.steps[-1].at
    )
    passed = wd.run_state is RunState.PASSED
    reward = (
        (variant.hypothetical_reward_on_pass if passed else 0.0)
        if variant.hypothetical_reward_on_pass is not None
        else None
    )
    return {
        "variant": variant.id,
        "scenario": path.id,
        "status": wd.run_state.value,
        "passed": passed,
        "final_observed_balance": report.balance,
        "final_observed_equity": report.equity,
        "max_observed_drawdown": drawdown,
        "max_observed_drawdown_pct_initial": 100 * drawdown / initial,
        "charged_simulated_trade_costs": costs,
        "costs_complete": wd.run_state is not RunState.FAILED,
        "hypothetical_evaluation_fee": variant.hypothetical_evaluation_fee,
        "hypothetical_operating_cost": variant.hypothetical_operating_cost,
        "hypothetical_reward": reward,
        "restores": restores,
        "failures": [v.rule for v in wd.state.violations if v.fatal],
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
    inputs = {
        "variants": [v.model_dump(mode="json") for v in variants],
        "paths": [p.model_dump(mode="json") for p in paths],
    }
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
                    r["status"] not in {"PASSED", "FAILED", "KILLED"} for r in sample
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
            "Static watchdog rules only; no overnight, aggregate exposure or trailing campaign support",
            "One flat episode at a time; no sizing, intrabar path or portfolio simulation",
            "Costs after a fatal intratrade trough are unknown, not assumed settled",
            "Rewards are explicit hypothetical inputs, never payouts or capital owned",
        ],
    }
