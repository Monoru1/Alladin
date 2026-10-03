from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from alladin.core.config import Settings
from alladin.core.enums import RunMode, Timeframe
from alladin.core.errors import AlladinError
from alladin.core.models import Bar
from alladin.core.workspace import MAGIC_RANGES, WorkspaceId, magic_for
from alladin.journal.repository import JournalRepository
from alladin.market.archive import ArchiveIncompleteError, MarketDataArchive
from alladin.orchestration.bootstrap import Components, build_services
from alladin.research.models import (
    ExperimentResult,
    ResearchSource,
    SourceType,
    StrategyExperiment,
    StrategyVersion,
)
from alladin.research.repository import ResearchRepository
from tests.conftest import T0, make_intent


def second(svc: Components, settings: Settings, tmp_path: Path) -> Components:
    other = build_services(settings, svc.broker, create_run=True, workspace=WorkspaceId.JAFAR,
                           db_url=f"sqlite:///{tmp_path / 'shared.db'}")
    assert other
    other.manager.start(other.run, other.broker.account_info())
    return other


@pytest.fixture
def pair(settings: Settings, broker: object, tmp_path: Path) -> tuple[Components, Components]:
    db = f"sqlite:///{tmp_path / 'shared.db'}"
    a = build_services(settings, broker, create_run=True, db_url=db)  # type: ignore[arg-type]
    assert a
    a.manager.start(a.run, a.broker.account_info())
    j = second(a, settings, tmp_path)
    return a, j


def test_shared_database_run_position_journal_and_kill_isolation(pair: tuple[Components, Components]) -> None:
    a, j = pair
    assert a.run.run_id != j.run.run_id and a.run.magic != j.run.magic
    for svc in pair:
        lower, upper = MAGIC_RANGES[svc.run.workspace]
        assert lower <= svc.run.magic < upper
        assert svc.run.account_binding and svc.run.account_binding.workspace == svc.run.workspace
        assert svc.execution.submit(make_intent(svc, opportunity_id="OPP-entry", proposal_id="AP-entry")).executed
    assert len(a.broker.positions()) == 2
    assert len(a.execution.my_positions()) == len(j.execution.my_positions()) == 1
    assert a.execution.owned_positions(RunMode.DEMO)[0].workspace is WorkspaceId.ALLADIN
    assert j.execution.owned_positions(RunMode.DEMO)[0].workspace is WorkspaceId.JAFAR
    assert [r.run_id for r in a.repo.list_runs()] == [a.run.run_id]
    assert [r.run_id for r in j.repo.list_runs()] == [j.run.run_id]
    assert a.repo.get_run(j.run.run_id) is None and j.repo.get_run(a.run.run_id) is None
    assert a.repo.trades_for_run(j.run.run_id) == [] and j.repo.events(a.run.run_id) == []
    assert a.repo.cycles(j.run.run_id) == []
    with pytest.raises(ValueError, match="workspace"):
        a.journal.log(j.run.run_id, "foreign", {})
    j.killswitch.activate("Jafar only")
    assert j.killswitch.is_active() and not a.killswitch.is_active()
    assert a.repo.verify_chain(a.run.run_id)[0] and j.repo.verify_chain(j.run.run_id)[0]


def experiment(ws: WorkspaceId) -> StrategyExperiment:
    return StrategyExperiment(workspace=ws, experiment_id="EXP-SAME", strategy_id="STRAT", strategy_version="1",
                              dataset=f"dataset-{ws}", period_start=T0, period_end=T0 + timedelta(days=1),
                              symbols=["EURUSD"], timeframes=["H1"], split="TRAIN")


def test_identical_research_ids_are_independent_in_shared_database(pair: tuple[Components, Components]) -> None:
    repos = [ResearchRepository.from_engine(s.repo.engine, s.run.workspace) for s in pair]
    for svc, repo in zip(pair, repos, strict=True):
        ws = svc.run.workspace
        repo.save_source(ResearchSource(workspace=ws, source_id="SOURCE", title=str(ws), retrieved_at=T0,
                                        source_type=SourceType.MANUAL))
        repo.save_version(StrategyVersion(workspace=ws, strategy_id="STRAT", version="1", code_hash=str(ws), created_at=T0))
        repo.save_experiment(experiment(ws))
        repo.save_result(ExperimentResult(workspace=ws, experiment_id="EXP-SAME", trades=1, wins=1, losses=0))
        assert repo.get_source("SOURCE").title == str(ws)  # type: ignore[union-attr]
        assert repo.list_versions()[0].code_hash == str(ws)
        assert repo.list_experiments() == [experiment(ws)]
        assert repo.get_result("EXP-SAME").workspace == ws  # type: ignore[union-attr]
        assert all(v == 1 for k, v in repo.stats().items() if k not in ("findings", "hypotheses"))
    with pytest.raises(ValueError, match="workspace"):
        repos[0].save_experiment(experiment(WorkspaceId.JAFAR))


def test_market_archive_and_cycle_ids_are_workspace_scoped(pair: tuple[Components, Components]) -> None:
    archives = [MarketDataArchive(s.repo.engine, workspace=s.run.workspace) for s in pair]
    for n, archive in enumerate(archives):
        bar = Bar(time=T0 - timedelta(hours=1), open=1 + n, high=1.1 + n, low=0.9 + n,
                  close=1 + n, tick_volume=100, available_at=T0, provenance=f"source-{n}")
        archive.store("EURUSD", Timeframe.H1, [bar], cycle_id="SAME-CYCLE", decision_at=T0)
        assert archive.load("EURUSD", Timeframe.H1)[0].close == 1 + n
        assert archive.load_cycle("SAME-CYCLE")["EURUSD"][Timeframe.H1][0].close == 1 + n
        assert archive.stats() == {"bars": 1, "symbols": 1}
    with pytest.raises(ArchiveIncompleteError):
        archives[1].load_cycle("ALLADIN-ONLY")


def test_resume_rejects_wrong_workspace_and_changed_account_fingerprint(pair: tuple[Components, Components], settings: Settings, tmp_path: Path) -> None:
    a, _ = pair
    db = f"sqlite:///{tmp_path / 'shared.db'}"
    with pytest.raises(AlladinError, match="introuvable"):
        build_services(settings, a.broker, run_id=a.run.run_id, workspace=WorkspaceId.JAFAR, db_url=db)
    real = a.broker.account_info
    a.broker.account_info = lambda: real().model_copy(update={"account_fingerprint": "f" * 64})  # type: ignore[method-assign]
    with pytest.raises(AlladinError, match="empreinte"):
        build_services(settings, a.broker, run_id=a.run.run_id, db_url=db)
    sent = len(a.broker.sent_orders)
    assert not a.execution.submit(make_intent(a)).executed
    assert len(a.broker.sent_orders) == sent


def test_magic_ranges_fail_closed_at_their_boundaries() -> None:
    assert magic_for(WorkspaceId.ALLADIN, 1) == 26_000_001
    assert magic_for(WorkspaceId.JAFAR, 1) == 27_000_001
    for ws in WorkspaceId:
        with pytest.raises(ValueError):
            magic_for(ws, 1_000_000)


def test_research_legacy_migration_preserves_immutable_evidence_and_allows_second_workspace(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as c:
        c.execute(text("CREATE TABLE research_experiments (experiment_id VARCHAR PRIMARY KEY, strategy_id VARCHAR, strategy_version VARCHAR, dataset VARCHAR, period_start DATETIME, period_end DATETIME, symbols TEXT, timeframes TEXT, parameters TEXT, split VARCHAR, created_at DATETIME)"))
        c.execute(text("INSERT INTO research_experiments VALUES ('EXP-SAME','STRAT','1','dataset-ALLADIN',:t,:e,'[\"EURUSD\"]','[\"H1\"]','{}','TRAIN',:t)"), {"t": T0.isoformat(), "e": (T0 + timedelta(days=1)).isoformat()})
        c.execute(text("CREATE TRIGGER research_experiments_no_update BEFORE UPDATE ON research_experiments BEGIN SELECT RAISE(ABORT, 'immutable'); END"))
    a = ResearchRepository.from_engine(engine)
    assert a.list_experiments() == [experiment(WorkspaceId.ALLADIN)]
    j = ResearchRepository.from_engine(engine, WorkspaceId.JAFAR)
    j.save_experiment(experiment(WorkspaceId.JAFAR))
    assert len(a.list_experiments()) == len(j.list_experiments()) == 1
    with pytest.raises(Exception, match="immutable"), engine.begin() as c:
        c.execute(text("UPDATE research_experiments SET dataset='bad'"))


def test_journal_legacy_migration_preserves_terminal_runs(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-journal.db'}")
    with engine.begin() as c:
        c.execute(text("CREATE TABLE runs (run_id VARCHAR PRIMARY KEY, seq INTEGER UNIQUE, profile_id VARCHAR, state VARCHAR, phase INTEGER, initial_balance FLOAT, broker VARCHAR, account VARCHAR, magic INTEGER, created_at VARCHAR, updated_at VARCHAR, watchdog_state TEXT)"))
        c.execute(text("INSERT INTO runs VALUES ('RUN-001',1,'ftmo_2step_demo','FAILED',1,100000,'MOCK','masked',26000001,:t,:t,:w)"), {"t": T0.isoformat(), "w": json.dumps({})})
        c.execute(text("CREATE TRIGGER runs_terminal_immutable BEFORE UPDATE ON runs WHEN OLD.state='FAILED' BEGIN SELECT RAISE(ABORT, 'immutable'); END"))
    repo = JournalRepository(engine)
    rec = repo.get_run("RUN-001")
    assert rec and rec.state == "FAILED" and rec.workspace is WorkspaceId.ALLADIN and rec.account_binding is None
    assert JournalRepository(engine, WorkspaceId.JAFAR).list_runs() == []


def test_persisted_identity_cannot_be_reassigned(pair: tuple[Components, Components]) -> None:
    a, j = pair
    result = a.execution.submit(make_intent(a))
    assert result.executed
    trade = a.repo.trades_for_run(a.run.run_id)[0]
    with pytest.raises(ValueError, match="immuable"):
        a.repo.update_trade(trade.trade_id, workspace=j.run.workspace)
    with pytest.raises(ValueError, match="immuable"):
        a.repo.update_paper_position("unused", run_id=j.run.run_id)
    assert a.repo.get_trade(trade.trade_id).workspace is WorkspaceId.ALLADIN  # type: ignore[union-attr]
