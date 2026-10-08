from dataclasses import replace
from datetime import timedelta

import pytest

from alladin.challenge.account_policy import AccountConstraints, DrawdownRule
from alladin.challenge.factory import (
    CampaignVariant,
    ScenarioPath,
    ScenarioStep,
    build_campaign,
    replay_scenario,
)
from tests.test_calendar_composite import NOW
from tests.test_challenge_factory import fixtures


def variant(mode, *, loss=5.0, lock=False, **updates):
    base = fixtures()[0][0]
    profile = base.challenge.model_copy(
        update={
            "official_rules": base.challenge.official_rules.model_copy(
                update={"daily_loss_pct": 20.0, "max_total_loss_pct": 30.0, "min_trading_days": 1}
            ),
            "phases": [base.challenge.phases[0].model_copy(update={"profit_target_pct": 20.0})],
        }
    )
    constraints = AccountConstraints(
        account_ref="synthetic",
        currency="USD",
        drawdown=DrawdownRule(mode=mode, loss_pct=loss, lock_floor_at_initial=lock),
    )
    return base.model_copy(
        update=dict({"challenge": profile, "firm": replace(base.firm, constraints=constraints)}, **updates)
    )


def path(*values):
    return ScenarioPath(
        id="synthetic-points",
        steps=tuple(ScenarioStep(at=NOW + timedelta(days=i), **value) for i, value in enumerate(values)),
    )


@pytest.mark.parametrize("mode", ["static", "trailing_balance", "trailing_equity", "trailing_eod"])
def test_drawdown_mode_from_explicit_transient_peak(mode):
    p = path({"gross_pnl_pct": 6.0, "worst_equity_pct": 0.0, "peak_equity_pct": 8.0})
    result = replay_scenario(variant(mode), p)
    expected_failure = mode == "trailing_equity"
    assert result["status"] == ("POLICY_FAILED" if expected_failure else "RUNNING")
    assert result["account_drawdown_observations"][0]["floor"] == (25750.0 if expected_failure else 23750.0)
    assert result["final_observed_balance"] == (25000.0 if expected_failure else 26500.0)
    assert result["final_observed_equity"] == (25000.0 if expected_failure else 26500.0)
    assert result["max_observed_drawdown"] == 2000.0
    assert result["failures"] == (["policy_drawdown"] if expected_failure else [])


@pytest.mark.parametrize("eod", [False, True])
def test_eod_requires_explicit_signal_and_survives_restart(eod):
    p = path(
        {"gross_pnl_pct": 6.0, "worst_equity_pct": 0.0, "end_of_day": eod},
        {"gross_pnl_pct": 3.0, "worst_equity_pct": -6.0, "restart": True},
    )
    result = replay_scenario(variant("trailing_eod"), p)
    assert result["status"] == ("POLICY_FAILED" if eod else "RUNNING")
    assert result["restores"] == 1
    assert result["account_drawdown_observations"][2]["floor"] == (25250.0 if eod else 23750.0)


def test_static_vs_trailing_balance_retreat():
    p = path(
        {"gross_pnl_pct": 6.0, "worst_equity_pct": 0.0}, {"gross_pnl_pct": 3.0, "worst_equity_pct": -6.0}
    )
    assert replay_scenario(variant("static"), p)["status"] == "RUNNING"
    result = replay_scenario(variant("trailing_balance"), p)
    assert result["status"] == "POLICY_FAILED"
    assert result["final_observed_equity"] == 25000.0
    assert len(result["decisions"]) == 2
    assert result["costs_complete"] is False


def test_lock_floor_does_not_authorize_exact_boundary():
    p = path({"gross_pnl_pct": 1.0, "worst_equity_pct": -1.0, "peak_equity_pct": 8.0})
    result = replay_scenario(variant("trailing_equity", lock=True), p)
    assert result["status"] == "POLICY_FAILED"
    assert result["account_drawdown_observations"][0]["floor"] == 25000.0


def test_phase_reset_is_explicit():
    from alladin.challenge.models import PhaseSpec

    base = variant("trailing_balance")
    profile = base.challenge.model_copy(
        update={
            "phases": [
                PhaseSpec(name="one", profit_target_pct=5.0),
                PhaseSpec(name="two", profit_target_pct=20.0),
            ]
        }
    )
    p = path({"gross_pnl_pct": 6.0, "worst_equity_pct": 0.0}, {"gross_pnl_pct": 1.0, "worst_equity_pct": 0.0})
    continuous = replay_scenario(base.model_copy(update={"challenge": profile}), p)
    reset = replay_scenario(
        base.model_copy(update={"challenge": profile, "reset_drawdown_on_phase": True}), p
    )
    assert continuous["drawdown_state"]["initial_balance"] == 25000.0
    assert reset["drawdown_state"]["initial_balance"] == 26500.0
    assert continuous["status"] == reset["status"] == "RUNNING"


def test_policy_failure_is_terminal_not_unfinished_or_rewarded():
    p = path(
        {"gross_pnl_pct": 6.0, "worst_equity_pct": 0.0, "peak_equity_pct": 8.0},
        {"gross_pnl_pct": 30.0, "worst_equity_pct": 0.0},
    )
    v = variant("trailing_equity", hypothetical_reward_on_pass=1000.0)
    result = build_campaign((v,), (p,))
    assert result["summaries"][0]["state_counts"] == {"POLICY_FAILED": 1}
    assert result["summaries"][0]["unfinished_scenarios"] == 0
    assert result["summaries"][0]["mean_hypothetical_reward"] == 0.0
    assert len(result["records"][0]["decisions"]) == 1
    assert result["summaries"][0]["real_world_pass_probability"] is None


@pytest.mark.parametrize(
    "field,value", [("sessions", None), ("forbid_weekend_hold", True), ("max_aggregate_positions", 1)]
)
def test_unsupported_constraints_never_silently_ignored(field, value):
    if field == "sessions":
        from alladin.market.sessions import SessionRules

        value = SessionRules()
    base = variant("static")
    constraints = base.firm.constraints.model_copy(update={field: value})
    with pytest.raises(ValueError):
        CampaignVariant.model_validate(
            base.model_copy(update={"firm": replace(base.firm, constraints=constraints)}).model_dump(
                mode="python"
            )
        )


def test_peak_below_close_or_infinite_rejected():
    for peak in (2.0, float("inf")):
        with pytest.raises(ValueError):
            path({"gross_pnl_pct": 3.0, "worst_equity_pct": 0.0, "peak_equity_pct": peak})


def test_observed_negative_equity_is_failure_without_fabricated_account_state():
    v = variant("static", loss=100.0)
    profile = v.challenge.model_copy(
        update={
            "official_rules": v.challenge.official_rules.model_copy(
                update={"daily_loss_pct": 100.0, "max_total_loss_pct": 100.0}
            ),
            "extra_rules": v.challenge.extra_rules.model_copy(update={"soft_daily_loss_pct": None}),
        }
    )
    v = v.model_copy(update={"challenge": profile})
    p = path(
        {"gross_pnl_pct": -49.0, "worst_equity_pct": -49.0}, {"gross_pnl_pct": 1.0, "worst_equity_pct": -60.0}
    )
    result = replay_scenario(v, p)
    assert result["status"] == "POLICY_FAILED"
    assert result["final_observed_equity"] == -2250.0
    assert result["drawdown_state"] is None
    assert result["drawdown_state_unavailable_reason"] == "NEGATIVE_EQUITY"
    assert result["account_drawdown_observations"][-1]["equity"] == -2250.0


def test_trailing_fixture_json_reproducible_across_processes(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    fixture = root / "tests/fixtures/policy/challenge_trailing_campaign.json"
    paths = []
    for seed in (1, 17):
        out = tmp_path / f"campaign-{seed}.json"
        subprocess.run(
            [
                sys.executable,
                str(root / "scripts/report_challenge_campaign.py"),
                "--fixture",
                str(fixture),
                "--output",
                str(out),
            ],
            env=dict(os.environ, PYTHONHASHSEED=str(seed)),
            check=True,
        )
        paths.append(out)
    assert paths[0].read_bytes() == paths[1].read_bytes()
