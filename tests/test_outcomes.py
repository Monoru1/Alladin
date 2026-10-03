from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError
from typer.testing import CliRunner

import alladin.cli as cli
from alladin.agents.mock import MockAgent
from alladin.api.app import create_app
from alladin.brain import Action
from alladin.core.enums import RunMode, Side
from alladin.core.workspace import WorkspaceId
from alladin.journal.models import EventType
from alladin.journal.repository import JournalRepository
from alladin.journal.service import JournalService
from alladin.market.paper import PaperExperimentEngine
from alladin.orchestration.bootstrap import build_services
from alladin.research.outcomes import (
    OutcomeEngine,
    OutcomeInput,
    OutcomeRepository,
    RewardPolicy,
    evaluate_outcome,
    outcome_summary,
)
from tests.conftest import T0, make_intent
from tests.test_position_lifecycle import action, opened


@pytest.fixture
def policy():
    return RewardPolicy(version="fixture-v1", pnl_weight=1, quality_weight=0.1, drawdown_weight=0.25, clip_abs=5)


def sample(**overrides):
    values = dict(workspace=WorkspaceId.ALLADIN, run_id="RUN-001", mode="DEMO", source_id="trade",
                  strategy_id="TEST", strategy_version="1", symbol="EURUSD", side=Side.BUY, currency="EUR",
                  opened_at=T0, closed_at=T0 + timedelta(hours=1), entry_price=100, exit_price=110,
                  original_volume=1, price_value_per_lot=20, initial_risk=100, gross_pnl=200,
                  commission_cashflow=-10, swap_cashflow=-5, net_pnl=185, mae_amount=50, mfe_amount=250,
                  excursion_samples=3, protected_initial=True, cost_basis="fixture")
    values.update(overrides)
    return OutcomeInput(**values)


def test_reward_components_cost_signs_duration_and_counterfactuals(policy):
    result = evaluate_outcome(sample(), policy, T0 + timedelta(hours=1))
    assert result.status == "ELIGIBLE" and result.holding_seconds == 3600
    assert result.net_r == 1.85 and result.mae_r == 0.5 and result.mfe_r == 2.5
    assert result.reward == pytest.approx(1.825)
    assert result.pnl_component == 1.85 and result.quality_component == 0.1 and result.drawdown_component == -0.125
    no_trade, hold = result.counterfactuals
    assert no_trade.net_pnl == 0 and no_trade.delta_net == 185
    assert hold.gross_pnl == 200 and hold.delta_gross == 0 and hold.net_pnl is None
    assert hold.basis == "MODELED_OPENING_CONVERSION"


@pytest.mark.parametrize("side,exit_price,gross", [(Side.BUY, 110, 200), (Side.SELL, 90, 200),
                                                   (Side.BUY, 90, -200), (Side.SELL, 110, -200)])
def test_hold_counterfactual_is_side_symmetric(policy, side, exit_price, gross):
    source = sample(side=side, exit_price=exit_price, gross_pnl=gross, net_pnl=gross - 15)
    outcome = evaluate_outcome(source, policy, source.closed_at)
    assert outcome.counterfactuals[1].gross_pnl == gross


@pytest.mark.parametrize("field,value", [("initial_risk", 0), ("net_pnl", None), ("commission_cashflow", None),
                                         ("mae_amount", None), ("excursion_samples", 0),
                                         ("protected_initial", None), ("currency", None), ("adopted", True)])
def test_missing_inputs_never_generate_fake_zero_reward(policy, field, value):
    result = evaluate_outcome(sample(**{field: value}), policy, T0 + timedelta(hours=1))
    assert result.status == "INCOMPLETE" and result.reward is None and result.warnings


@pytest.mark.parametrize("field,value", [("net_pnl", float("nan")), ("mae_amount", -1), ("original_volume", 0),
                                         ("closed_at", T0 - timedelta(seconds=1)), ("closed_at", T0.replace(tzinfo=None)),
                                         ("entry_price", 0)])
def test_bad_source_is_rejected(field, value):
    with pytest.raises(ValidationError):
        sample(**{field: value})


def test_quality_is_a_protection_proxy_and_reward_is_bounded(policy):
    good = evaluate_outcome(sample(), policy, T0 + timedelta(hours=1))
    bad = evaluate_outcome(sample(protection_incidents=1), policy, T0 + timedelta(hours=1))
    assert bad.quality_score == -1 and bad.reward == pytest.approx(good.reward - 0.2)
    high = evaluate_outcome(sample(gross_pnl=10000, net_pnl=9985), policy, T0 + timedelta(hours=1))
    assert high.reward == 5 and high.reward_unclipped > 5
    with pytest.raises(ValidationError):
        RewardPolicy.model_validate({**policy.model_dump(), "drawdown_weight": float("inf")})


def close_demo(svc):
    result = svc.execution.submit(make_intent(svc))
    assert result.executed
    svc.monitor.sync()
    position = svc.execution.my_positions()[0]
    svc.broker.advance(timedelta(seconds=60))
    svc.broker.set_price("EURUSD", position.price_open + 0.001, position.price_open + 0.00112)
    svc.monitor.sync()
    assert svc.execution.close_position(position.ticket, "outcome test")
    svc.monitor.sync()
    return svc.repo.get_trade(result.trade_id)


def test_demo_collection_is_immutable_atomic_idempotent_and_readonly(svc):
    trade = close_demo(svc)
    sent = len(svc.broker.sent_orders)
    report = svc.outcomes.collect_run(svc.run.run_id)
    assert len(report.created) == 1 and not report.errors
    saved = svc.outcomes.store.list(svc.run.run_id)[0]
    assert saved.status == "ELIGIBLE" and saved.source.source_id == trade.trade_id
    assert saved.source.initial_risk == trade.risk_amount and saved.source.currency == svc.broker.account_info().currency
    assert saved.source.excursion_samples >= 3
    assert svc.outcomes.collect_run(svc.run.run_id).unchanged == 1
    assert len(svc.repo.events(svc.run.run_id, [EventType.OUTCOME.value])) == 1
    assert len(svc.broker.sent_orders) == sent and svc.repo.verify_chain(svc.run.run_id)[0]
    for statement in ("UPDATE trade_outcomes SET payload='{}'", "DELETE FROM trade_outcomes"):
        with svc.repo.engine.begin() as c, pytest.raises(DatabaseError, match="immutable"):
            c.execute(text(statement))


def test_outcome_and_audit_rollback_together(svc):
    close_demo(svc)
    with svc.repo.engine.begin() as c:
        c.execute(text("CREATE TRIGGER fail_outcome_audit BEFORE INSERT ON journal_events WHEN NEW.type='learning.outcome' BEGIN SELECT RAISE(ABORT, 'crash'); END"))
    report = svc.outcomes.collect_run(svc.run.run_id)
    assert report.errors and not report.created
    assert not svc.outcomes.store.list(svc.run.run_id)
    with svc.repo.engine.begin() as c:
        c.execute(text("DROP TRIGGER fail_outcome_audit"))
    assert len(svc.outcomes.collect_run(svc.run.run_id).created) == 1


def test_paper_partial_economics_restore_and_reward(svc):
    paper = opened(svc, RunMode.PAPER)
    assert paper
    svc.broker.advance(timedelta(seconds=60))
    pos = paper.open_positions()[0]
    svc.broker.set_price(pos.symbol, pos.entry_price + 0.001, pos.entry_price + 0.00112)
    paper.tick_all()
    assert svc.execution.submit_position_action(action(svc, RunMode.PAPER, Action.PARTIAL_CLOSE, paper), RunMode.PAPER, paper).confirmed
    restored = PaperExperimentEngine(svc.broker, svc.run.run_id, repo=svc.repo)
    restored.restore()
    svc.broker.advance(timedelta(seconds=60))
    svc.broker.set_price(pos.symbol, pos.entry_price + 0.002, pos.entry_price + 0.00212)
    assert svc.execution.submit_position_action(action(svc, RunMode.PAPER, Action.CLOSE, restored, cycle="final"), RunMode.PAPER, restored).confirmed
    report = svc.outcomes.collect_run(svc.run.run_id)
    assert not report.errors and len(report.created) == 1
    result = svc.outcomes.store.list(svc.run.run_id)[0]
    assert result.source.mode == "PAPER" and result.status == "ELIGIBLE"
    assert result.source.net_pnl == pytest.approx(300)
    assert result.counterfactuals[1].gross_pnl == pytest.approx(400)
    assert result.counterfactuals[1].delta_gross == pytest.approx(-100)
    assert result.source.mfe_amount == pytest.approx(300)
    assert svc.broker.sent_orders == []


def test_auto_capture_in_observe_cycle_does_not_send(svc):
    close_demo(svc)
    sent = len(svc.broker.sent_orders)
    outcome = svc.engine(MockAgent()).run_cycle()
    assert outcome.cycle_id and len(svc.outcomes.store.list(svc.run.run_id)) == 1
    assert len(svc.broker.sent_orders) == sent
    assert svc.outcomes.collect_run(svc.run.run_id, include_existing=False).created == []


def test_policy_versions_do_not_overwrite_or_double_count_currency_totals(svc, policy):
    close_demo(svc)
    assert len(svc.outcomes.collect_run(svc.run.run_id).created) == 1
    alternate = OutcomeEngine(svc.repo, svc.journal, policy)
    assert len(alternate.collect_run(svc.run.run_id).created) == 1
    rows = alternate.store.list(svc.run.run_id)
    assert len(rows) == 2 and len(outcome_summary(rows)) == 2
    assert all(g["outcomes"] == 1 for g in outcome_summary(rows))


def test_file_restart_and_cli_refresh_show_do_not_connect(settings, broker, tmp_path: Path, monkeypatch):
    svc = build_services(settings, broker, create_run=True)
    assert svc
    svc.manager.start(svc.run, broker.account_info())
    close_demo(svc)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "make_broker", lambda *args: pytest.fail("offline outcomes connected a broker"))
    runner = CliRunner()
    refresh = runner.invoke(cli.app, ["outcomes", "refresh", svc.run.run_id])
    assert refresh.exit_code == 0, refresh.output
    svc.repo.engine.dispose()
    repo = JournalRepository.from_url(settings.db_url)
    saved = OutcomeRepository(repo, read_only=True).list(svc.run.run_id)
    assert len(saved) == 1
    repeat = runner.invoke(cli.app, ["outcomes", "refresh", svc.run.run_id])
    assert repeat.exit_code == 0 and '"unchanged": 1' in repeat.output
    shown = runner.invoke(cli.app, ["outcomes", "show", svc.run.run_id])
    assert shown.exit_code == 0 and saved[0].outcome_id in shown.output
    assert runner.invoke(cli.app, ["outcomes", "show", "RUN-foreign"]).exit_code == 2


def test_api_reads_snapshots_only_and_workspace_scope(svc):
    close_demo(svc)
    api = TestClient(create_app(svc.settings, svc.repo, svc.broker))
    before = api.get("/api/outcomes").json()
    assert not before["outcomes"]
    assert len(svc.repo.events(svc.run.run_id, [EventType.OUTCOME.value])) == 0
    svc.outcomes.collect_run(svc.run.run_id)
    response = api.get("/api/outcomes").json()
    assert response["outcomes"][0]["status"] == "ELIGIBLE"
    assert response["summary_scope"] == "RETURNED_ROWS"
    assert "outcomes-body" in api.get("/").text
    assert api.post("/api/outcomes").status_code == 405
    foreign = JournalRepository(svc.repo.engine, WorkspaceId.JAFAR)
    assert OutcomeRepository(foreign, read_only=True).list(svc.run.run_id) == []
    with pytest.raises(ValueError, match="workspace"):
        OutcomeRepository(foreign).persist(svc.outcomes.store.list(svc.run.run_id)[0], JournalService(foreign))


def test_closed_source_cannot_be_silently_reinterpreted(svc):
    paper = opened(svc, RunMode.PAPER)
    assert paper
    paper.close_position_by_id(paper.open_positions()[0].paper_id)
    svc.outcomes.collect_run(svc.run.run_id)
    saved = svc.outcomes.store.list(svc.run.run_id)[0]
    svc.repo.update_paper_position(saved.source.source_id, realized_pnl=999)
    report = svc.outcomes.collect_run(svc.run.run_id)
    assert report.errors and report.created == []
    assert svc.outcomes.store.list(svc.run.run_id)[0] == saved


def test_forged_reward_cannot_be_persisted(svc, policy):
    source = sample(run_id=svc.run.run_id, closed_at=T0)
    outcome = evaluate_outcome(source, policy, T0)
    with pytest.raises(ValueError, match="deterministic"):
        svc.outcomes.store.persist(outcome.model_copy(update={"reward": 123}), svc.journal)


def test_net_rebate_and_currency_groups_are_not_conflated(policy):
    first = evaluate_outcome(sample(commission_cashflow=10, swap_cashflow=5, net_pnl=215), policy, T0 + timedelta(hours=1))
    other = evaluate_outcome(sample(mode="PAPER", currency="USD"), policy, T0 + timedelta(hours=1))
    groups = outcome_summary([first, other])
    assert len(groups) == 2 and first.net_r == 2.15


def test_unreliable_close_history_remains_unresolved(svc):
    result = svc.execution.submit(make_intent(svc))
    assert result.executed
    ticket = result.position_ticket
    assert svc.execution.close_position(ticket)
    # Broker position is gone but only half the exit history has arrived.
    out = svc.broker._deals[-1]
    original = out.volume
    out.volume = original / 2
    report = svc.monitor.sync()
    assert report.unresolved_closed == [ticket]
    assert svc.repo.get_trade(result.trade_id).status == "OPEN"
    assert not svc.outcomes.collect_run(svc.run.run_id).created
    out.volume = original
    assert svc.monitor.sync().newly_closed == [result.trade_id]
    assert len(svc.outcomes.collect_run(svc.run.run_id).created) == 1


def test_demo_excursions_include_realized_partial_gross(svc):
    opened(svc, RunMode.DEMO)
    original = svc.execution.my_positions()[0]
    svc.broker.set_price(original.symbol, original.price_open + 0.001, original.price_open + 0.00112)
    svc.monitor.sync()
    assert svc.execution.submit_position_action(action(svc, RunMode.DEMO, Action.PARTIAL_CLOSE, None), RunMode.DEMO).confirmed
    svc.broker.set_price(original.symbol, original.price_open + 0.002, original.price_open + 0.00212)
    svc.monitor.sync()
    record = svc.repo.trades_for_run(svc.run.run_id)[0]
    assert record.mfe == pytest.approx(300)  # 100 realized + 200 remaining floating
    assert svc.execution.close_position(original.ticket)
    svc.monitor.sync()
    assert svc.outcomes.collect_run(svc.run.run_id).created
    saved = svc.outcomes.store.list(svc.run.run_id)[0]
    assert saved.source.net_pnl == pytest.approx(300) and saved.source.mfe_amount == pytest.approx(300)
    assert saved.counterfactuals[1].gross_pnl == pytest.approx(400)


def test_monitor_refuses_a_switched_account_before_learning(svc):
    from alladin.core.enums import AccountType
    from alladin.core.errors import ExecutionBlockedError
    result = svc.execution.submit(make_intent(svc))
    assert result.executed
    svc.broker._account_type = AccountType.LIVE
    with pytest.raises(ExecutionBlockedError, match="binding"):
        svc.monitor.sync()
    assert svc.repo.get_trade(result.trade_id).status == "OPEN"
    assert not svc.outcomes.collect_run(svc.run.run_id).created


def test_learning_failure_never_rewrites_brain_or_blocks_cycle(svc):
    engine = svc.engine(MockAgent())
    before = engine.brain
    svc.outcomes.collect_run = lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("research unavailable"))
    result = engine.run_cycle()
    assert result.decision in ("TRADE", "NO_TRADE") and engine.brain is before
    alerts = svc.repo.events(svc.run.run_id, [EventType.INFO.value])
    assert any(e.payload.get("alert") == "outcome collection failed" for e in alerts)
    assert not svc.broker.sent_orders


def test_corrupt_snapshot_is_refused_by_api(svc):
    close_demo(svc)
    svc.outcomes.collect_run(svc.run.run_id)
    with svc.repo.engine.begin() as c:
        c.execute(text("DROP TRIGGER outcomes_no_update"))
        c.execute(text("UPDATE trade_outcomes SET payload_hash='corrupt'"))
    with pytest.raises(ValueError, match="integrity"):
        svc.outcomes.store.list(svc.run.run_id)
    api = TestClient(create_app(svc.settings, svc.repo, svc.broker))
    assert api.get("/api/outcomes").status_code == 409


def test_two_collectors_cannot_duplicate_outcome_or_audit(settings, broker):
    from concurrent.futures import ThreadPoolExecutor
    svc = build_services(settings, broker, create_run=True)
    assert svc
    svc.manager.start(svc.run, broker.account_info())
    close_demo(svc)
    other_repo = JournalRepository.from_url(settings.db_url)
    other = OutcomeEngine(other_repo, JournalService(other_repo, svc.journal.clock), svc.outcomes.policy)
    with ThreadPoolExecutor(max_workers=2) as executor:
        reports = list(executor.map(lambda collector: collector.collect_run(svc.run.run_id), [svc.outcomes, other]))
    assert sum(len(r.created) for r in reports) == 1 and all(not r.errors for r in reports)
    assert len(svc.repo.events(svc.run.run_id, [EventType.OUTCOME.value])) == 1
    assert svc.repo.verify_chain(svc.run.run_id)[0]
