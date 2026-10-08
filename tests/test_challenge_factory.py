import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from scripts.report_challenge_campaign import fixture_report

from alladin.challenge.account_policy import AccountConstraints
from alladin.challenge.factory import (
    CampaignVariant,
    ScenarioPath,
    ScenarioStep,
    build_campaign,
    replay_scenario,
)


def fixtures():
    data = json.loads((Path(__file__).parent / "fixtures/policy/challenge_campaign.json").read_text())
    return tuple(CampaignVariant.model_validate(v) for v in data["variants"]), tuple(
        ScenarioPath.model_validate(p) for p in data["paths"]
    )


def test_campaign_reproducible_paired_and_no_performance_claim():
    a = fixture_report()
    assert a == fixture_report()
    assert len(a["records"]) == 16
    assert a["execution_authorized"] is False
    for s in a["summaries"]:
        assert s["scenario_count"] == 4
        assert s["state_counts"] == {"FAILED": 1, "PASSED": 1, "RUNNING": 2}
        assert s["scenario_pass_fraction"] == 0.25
        assert s["unfinished_scenarios"] == 2
        assert s["real_world_pass_probability"] is None
        assert s["real_cash_generated"] is None
        assert s["mean_hypothetical_reward"] is None
    rows = a["records"]
    small = next(r for r in rows if r["variant"] == "synthetic-moderate-25000" and r["scenario"] == "gains")
    large = next(r for r in rows if r["variant"] == "synthetic-moderate-100000" and r["scenario"] == "gains")
    assert large["final_observed_balance"] == 4 * small["final_observed_balance"]
    assert large["charged_simulated_trade_costs"] == 4 * small["charged_simulated_trade_costs"]


def test_fatal_trough_stops_path_before_future_recovery():
    variants, paths = fixtures()
    result = replay_scenario(variants[0], paths[1])
    assert result["status"] == "FAILED"
    assert result["failures"] == ["max_daily_loss"]
    assert len(result["decisions"]) == 1
    assert result["final_observed_balance"] == 25000.0
    assert result["final_observed_equity"] == 23475.0
    assert result["max_observed_drawdown"] == 1525.0
    assert result["costs_complete"] is False


def test_announcements_outages_and_restart_causal():
    variants, paths = fixtures()
    result = replay_scenario(variants[0], paths[2])
    assert [d["reason"] for d in result["decisions"][:2]] == ["FIRM_RESTRICTED_EVENT", "CALENDAR_MISSING"]
    assert result["final_observed_balance"] == 25725.0
    assert result["restores"] == 1
    assert result["status"] == "RUNNING"


def test_restart_preserves_rules_and_target():
    variants, paths = fixtures()
    path = paths[0]
    with_restart = path.model_copy(
        update={"steps": tuple(s.model_copy(update={"restart": True}) for s in path.steps)}
    )
    a = replay_scenario(variants[0], path)
    b = replay_scenario(variants[0], with_restart)
    assert a["final_observed_balance"] == b["final_observed_balance"]
    assert a["status"] == b["status"] == "PASSED"
    assert b["restores"] == 2


def test_hypothetical_rewards_only_explicit_and_hash_sensitive():
    variants, paths = fixtures()
    variant = variants[0].model_copy(update={"hypothetical_reward_on_pass": 1000.0})
    a = build_campaign((variants[0],), paths)
    b = build_campaign((variant,), paths)
    assert a["input_sha256"] != b["input_sha256"]
    assert b["summaries"][0]["mean_hypothetical_reward"] == 250.0
    assert b["summaries"][0]["real_cash_generated"] is None


@pytest.mark.parametrize(
    "updates",
    [
        {"gross_pnl_pct": float("nan")},
        {"cost_pct": -1.0},
        {"worst_equity_pct": 1.0},
        {"gross_pnl_pct": -5.0, "worst_equity_pct": 0.0},
        {"restart": "true"},
    ],
)
def test_bad_step_rejected(updates):
    values = {"at": datetime(2026, 10, 8, 12, tzinfo=UTC), "gross_pnl_pct": 1.0, "worst_equity_pct": 0.0}
    with pytest.raises(ValueError):
        ScenarioStep(**dict(values, **updates))


def test_chronology_and_scope_rejected():
    variants, paths = fixtures()
    step = paths[0].steps[0]
    with pytest.raises(ValueError):
        ScenarioPath(id="duplicate", steps=(step, step))
    with pytest.raises(ValueError):
        ScenarioPath(
            id="short", steps=(step, step.model_copy(update={"at": step.at + timedelta(minutes=60)}))
        )
    with pytest.raises(ValueError):
        build_campaign((variants[0], variants[0]), paths)
    with pytest.raises(ValueError):
        build_campaign(variants, ())
    data = variants[0].model_dump(mode="python")
    with pytest.raises(ValueError):
        CampaignVariant.model_validate(dict(data, simulation_only=False))
    data["firm"] = replace(
        variants[0].firm, constraints=AccountConstraints(account_ref="fixture", currency="USD")
    )
    with pytest.raises(ValueError):
        CampaignVariant.model_validate(data)


def test_phase_progression_uses_existing_watchdog_baseline():
    from alladin.challenge.models import PhaseSpec

    variants, paths = fixtures()
    profile = variants[0].challenge.model_copy(
        update={
            "phases": [
                PhaseSpec(name="one", profit_target_pct=2.0),
                PhaseSpec(name="two", profit_target_pct=2.0),
            ],
            "official_rules": variants[0].challenge.official_rules.model_copy(update={"min_trading_days": 1}),
        }
    )
    v = variants[0].model_copy(update={"challenge": profile})
    result = replay_scenario(v, paths[0])
    assert result["status"] == "PASSED"
    assert result["final_observed_balance"] == pytest.approx(25000 * 1.029**2)
