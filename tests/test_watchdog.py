"""ChallengeWatchdog : drawdowns, objectifs, phases, consistency, irréversibilité de FAILED."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy.exc import DatabaseError

from alladin.challenge.models import ChallengeProfile
from alladin.challenge.watchdog import ChallengeWatchdog
from alladin.core.enums import RuleSource, RunState
from alladin.core.errors import IrreversibleStateError
from alladin.core.models import AccountSnapshot
from alladin.orchestration.bootstrap import Components
from tests.conftest import T0, make_intent


def snap(balance: float, equity: float | None = None, now: datetime = T0) -> AccountSnapshot:
    eq = balance if equity is None else equity
    return AccountSnapshot(
        login_masked="***",
        server="t",
        currency="USD",
        balance=balance,
        equity=eq,
        margin=0,
        free_margin=eq,
        floating_pnl=eq - balance,
        account_type="DEMO",
        timestamp=now,  # type: ignore[arg-type]
    )


def running(profile: ChallengeProfile) -> ChallengeWatchdog:
    wd = ChallengeWatchdog.create(profile, "RUN-T", 100_000)
    wd.start(snap(100_000), T0)
    return wd


def test_initial_headroom_matches_profile(profile: ChallengeProfile) -> None:
    rep = running(profile).update(snap(100_000), T0)
    assert rep.daily_headroom == 5_000 and rep.total_headroom == 10_000
    assert rep.target_level == 110_000 and rep.can_open_new_positions


def test_daily_drawdown_violation_fails_the_run(profile: ChallengeProfile) -> None:
    wd = running(profile)
    rep = wd.update(snap(100_000, 94_900), T0 + timedelta(hours=1))  # 5,1 % sous le départ du jour
    assert wd.run_state is RunState.FAILED
    v = rep.violations[-1]
    assert v.rule == "max_daily_loss" and v.source is RuleSource.OFFICIAL and v.fatal
    assert not rep.can_open_new_positions


def test_daily_loss_counts_floating_loss(profile: ChallengeProfile) -> None:
    wd = running(profile)
    wd.update(snap(100_000, 95_000.01), T0)
    assert wd.run_state is RunState.RUNNING  # exactement au-dessus du seuil
    wd.update(snap(100_000, 95_000.0), T0)
    assert wd.run_state is RunState.FAILED


def test_total_drawdown_violation_across_days(profile: ChallengeProfile) -> None:
    wd = running(profile)
    for day, eq in enumerate([96_000, 92_000], start=1):  # chaque jour reste sous 5 % de perte journalière
        wd.update(snap(eq), T0 + timedelta(days=day))
        assert wd.run_state is RunState.RUNNING
    rep = wd.update(snap(92_000, 89_900), T0 + timedelta(days=2, hours=2))
    assert wd.run_state is RunState.FAILED
    assert rep.violations[-1].rule == "max_total_loss"


def test_soft_daily_limit_blocks_new_orders_but_is_not_fatal(profile: ChallengeProfile) -> None:
    wd = running(profile)
    rep = wd.update(snap(100_000, 96_900), T0)  # -3,1 % : règle expérimentale ALLADIN (3 %)
    assert wd.run_state is RunState.RUNNING and not rep.can_open_new_positions
    soft = [v for v in rep.violations if v.rule == "soft_daily_loss"]
    assert soft and soft[0].source is RuleSource.EXTRA and not soft[0].fatal
    # le lendemain, nouvelle journée (perte clôturée : solde = equity = 96 900) : le blocage est levé
    rep2 = wd.update(snap(96_900), T0 + timedelta(days=1))
    assert rep2.can_open_new_positions


def _win_days(wd: ChallengeWatchdog, pnls: list[float], start_balance: float) -> float:
    bal = start_balance
    for i, p in enumerate(pnls, start=1):
        now = T0 + timedelta(days=i)
        wd.update(snap(bal), now)
        wd.record_trade_opened(now)
        bal += p
        wd.record_closed_pnl(p, now + timedelta(hours=1))
        wd.update(snap(bal), now + timedelta(hours=1))
    return bal


def test_phase1_target_then_phase2_transition(profile: ChallengeProfile) -> None:
    wd = running(profile)
    bal = _win_days(wd, [2_000] * 5, 100_000)  # +10 %, 5 jours, best day 20 %
    assert bal == 110_000
    assert wd.phase_number == 2 and wd.run_state is RunState.RUNNING
    assert wd.state.baseline_balance == 110_000  # nouvelle base de calcul
    assert wd.state.phase_results[0].phase == 1 and wd.state.trading_days == []
    rep = wd.update(snap(110_000), T0 + timedelta(days=6))
    assert rep.target_pct == 5 and rep.target_level == 115_500


def test_phase2_target_passes_the_challenge(profile: ChallengeProfile) -> None:
    wd = running(profile)
    bal = _win_days(wd, [2_000] * 5, 100_000)
    for i in range(1, 6):  # 5 jours x 1 100 = +5 %
        now = T0 + timedelta(days=5 + i)
        wd.update(snap(bal), now)
        wd.record_trade_opened(now)
        bal += 1_100
        wd.record_closed_pnl(1_100, now + timedelta(hours=1))
        wd.update(snap(bal), now + timedelta(hours=1))
    assert wd.run_state is RunState.PASSED


def test_target_reached_but_min_trading_days_not_met(profile: ChallengeProfile) -> None:
    wd = running(profile)
    now = T0 + timedelta(days=1)
    wd.record_trade_opened(now)
    wd.record_closed_pnl(10_000, now)
    rep = wd.update(snap(110_000), now)
    assert wd.run_state is RunState.TARGET_REACHED and wd.phase_number == 1
    assert (
        rep.trading_days == 1 and rep.can_open_new_positions
    )  # on peut encore trader pour valider les jours


def test_consistency_rule_blocks_pass_when_best_day_dominates(profile: ChallengeProfile) -> None:
    wd = running(profile)
    _win_days(wd, [7_000, 1_000, 1_000, 1_000], 100_000)  # best day = 70 % > 50 %
    assert wd.run_state is RunState.TARGET_REACHED and wd.phase_number == 1
    rep = wd.update(snap(110_000), T0 + timedelta(days=5))
    assert rep.best_day_share_pct == pytest.approx(70.0)


def test_consistency_rule_is_optional(profile: ChallengeProfile) -> None:
    profile.extra_rules.consistency.enabled = False
    wd = running(profile)
    _win_days(wd, [7_000, 1_000, 1_000, 1_000], 100_000)
    assert wd.phase_number == 2


def test_open_positions_prevent_passing_when_flat_required(profile: ChallengeProfile) -> None:
    wd = running(profile)
    bal = _win_days(wd, [2_500] * 3, 100_000)
    now = T0 + timedelta(days=4)
    wd.record_trade_opened(now)
    wd.record_closed_pnl(2_500, now)
    bal += 2_500
    wd.update(snap(bal), now, open_positions=1)
    assert wd.phase_number == 1 and wd.run_state is RunState.TARGET_REACHED
    wd.update(snap(bal), now, open_positions=0)
    assert wd.phase_number == 2


def test_phase_time_limit_14_days_is_an_extra_rule(profile: ChallengeProfile) -> None:
    wd = running(profile)
    wd.update(snap(100_000), T0 + timedelta(days=13))
    assert wd.run_state is RunState.RUNNING
    rep = wd.update(snap(100_000), T0 + timedelta(days=14, minutes=1))
    assert wd.run_state is RunState.FAILED
    assert rep.violations[-1].rule == "max_days_per_phase" and rep.violations[-1].source is RuleSource.EXTRA


def test_failed_is_irreversible(profile: ChallengeProfile) -> None:
    wd = running(profile)
    wd.update(snap(100_000, 90_000), T0)
    assert wd.run_state is RunState.FAILED
    for action in (wd.resume, wd.pause, wd.kill):
        with pytest.raises(IrreversibleStateError):
            action()
    with pytest.raises(IrreversibleStateError):
        wd.start(snap(100_000), T0)
    # un retour miraculeux de l'equity ne ressuscite pas le run
    rep = wd.update(snap(120_000), T0 + timedelta(days=1))
    assert wd.run_state is RunState.FAILED and not rep.can_open_new_positions


def test_failed_run_is_immutable_in_database(svc: Components, broker) -> None:  # type: ignore[no-untyped-def]
    broker.inject_pnl(-6_000)
    svc.monitor.sync()
    assert svc.run.watchdog.run_state is RunState.FAILED
    rec = svc.repo.get_run(svc.run.run_id)
    assert rec and rec.state == "FAILED"
    with pytest.raises(DatabaseError):
        svc.repo.update_run(svc.run.run_id, "RUNNING", 1, {}, broker.now())
    svc.manager.persist(svc.run)  # no-op silencieux
    res = svc.execution.submit(make_intent(svc))
    assert res.status.value == "REJECTED_RISK"
    assert broker.positions() == []


def test_watchdog_state_survives_restart(svc: Components, broker) -> None:  # type: ignore[no-untyped-def]
    broker.inject_pnl(-1_000)
    svc.monitor.sync()
    again = svc.manager.load_run(svc.run.run_id, svc.profile)
    assert again.watchdog.state.day_start_balance == svc.run.watchdog.state.day_start_balance
    assert again.watchdog.run_state is RunState.RUNNING
