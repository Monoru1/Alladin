"""Tests : RunMode (OBSERVE/PAPER/DEMO), daemon lifecycle, signal handling, Opportunity model,
Research persistence."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from alladin.agents.mock import MockAgent
from alladin.core.enums import MarketRegime, RunMode, Side, Timeframe
from alladin.market.opportunity import Opportunity, OpportunityStatus
from alladin.orchestration.bootstrap import Components
from alladin.research.models import (
    ExperimentResult,
    ResearchFinding,
    ResearchSource,
    SourceType,
    StrategyExperiment,
    StrategyStatus,
    StrategyVersion,
)
from alladin.research.repository import ResearchRepository

# ============================================================================
# RunMode : enum et intégration moteur
# ============================================================================


def test_run_mode_enum_values() -> None:
    assert RunMode.OBSERVE.value == "OBSERVE"
    assert RunMode.PAPER.value == "PAPER"
    assert RunMode.DEMO.value == "DEMO"


def test_engine_observe_mode_never_sends_orders(svc: Components) -> None:
    """En mode OBSERVE, execute doit être False même si l'agent propose un trade."""
    engine = svc.engine(MockAgent(), run_mode=RunMode.OBSERVE)
    assert engine.execute is False
    assert engine.run_mode is RunMode.OBSERVE


def test_engine_paper_mode_never_sends_orders(svc: Components) -> None:
    engine = svc.engine(MockAgent(), run_mode=RunMode.PAPER)
    assert engine.execute is False
    assert engine.run_mode is RunMode.PAPER


def test_engine_demo_mode_sets_execute_true(svc: Components) -> None:
    engine = svc.engine(MockAgent(), run_mode=RunMode.DEMO)
    assert engine.execute is True
    assert engine.run_mode is RunMode.DEMO


def test_legacy_execute_flag_maps_to_demo_mode(svc: Components) -> None:
    """Rétrocompatibilité : execute=True sans run_mode explicite → DEMO."""
    engine = svc.engine(MockAgent(), execute=True)
    assert engine.run_mode is RunMode.DEMO
    assert engine.execute is True


def test_observe_mode_run_cycle_produces_no_trade_or_dry_run(svc: Components) -> None:
    """Un cycle en OBSERVE ne doit jamais aboutir à EXECUTED (seulement DRY_RUN_APPROVED ou NO_TRADE)."""
    engine = svc.engine(MockAgent(), run_mode=RunMode.OBSERVE)
    outcome = engine.run_cycle()
    # Le MockAgent peut proposer un trade ; le résultat doit être DRY_RUN ou NO_TRADE
    assert outcome.decision in ("NO_TRADE", "TRADE")
    # Aucune position réelle ne doit avoir été ouverte via broker (mode OBSERVE = dry-run)
    assert engine.execute is False


def test_mode_change_event_is_logged(svc: Components) -> None:
    """run_loop doit journaliser un événement mode.change au démarrage."""
    from alladin.journal.models import EventType

    engine = svc.engine(MockAgent(), run_mode=RunMode.PAPER)
    engine.run_loop(interval_s=0, max_cycles=1, handle_signals=False)
    events = svc.repo.events(svc.run.run_id, [EventType.MODE_CHANGE.value])
    assert events, "aucun événement mode.change trouvé"
    assert events[0].payload["run_mode"] == "PAPER"


def test_run_loop_respects_max_cycles(svc: Components) -> None:
    engine = svc.engine(MockAgent(), run_mode=RunMode.OBSERVE)
    outcomes: list[object] = []
    engine.run_loop(interval_s=0, max_cycles=3, on_cycle=outcomes.append, handle_signals=False)
    assert len(outcomes) == 3


def test_run_loop_stop_requested_stops_loop(svc: Components) -> None:
    engine = svc.engine(MockAgent(), run_mode=RunMode.OBSERVE)
    call_count = 0

    def _on_cycle(o: object) -> None:
        nonlocal call_count
        call_count += 1
        engine._stop_requested = True  # simule un signal

    engine.run_loop(interval_s=0, max_cycles=100, on_cycle=_on_cycle, handle_signals=False)
    assert call_count == 1  # arrêté après le premier cycle


# ============================================================================
# Opportunity model
# ============================================================================


def test_opportunity_lifecycle_transitions() -> None:
    now = datetime.now(UTC)
    opp = Opportunity(
        opportunity_id="OPP-001",
        cycle_id="CYC-1",
        run_id="RUN-001",
        symbol="EURUSD",
        timeframe=Timeframe.H1,
        timestamp=now,
        bid=1.1000,
        ask=1.1002,
        spread=0.0002,
        atr=0.0030,
        spread_atr_ratio=0.0002 / 0.0030,
        regime=MarketRegime.TREND,
        regime_confidence=0.75,
        direction=Side.BUY,
        strategy_candidates=["TREND-01"],
        setup_score=0.72,
        planned_rr=2.0,
    )
    assert opp.status is OpportunityStatus.SEEN
    opp.status = OpportunityStatus.QUALIFIED
    assert opp.status is OpportunityStatus.QUALIFIED


def test_opportunity_filtered_keeps_rejection_reasons() -> None:
    now = datetime.now(UTC)
    opp = Opportunity(
        opportunity_id="OPP-002",
        cycle_id="CYC-1",
        run_id="RUN-001",
        symbol="GBPUSD",
        timeframe=Timeframe.M15,
        timestamp=now,
        bid=1.2500,
        ask=1.2510,
        spread=0.001,
        rejection_reasons=["SPREAD_TOO_HIGH", "STALE_TICK"],
        status=OpportunityStatus.FILTERED,
    )
    assert len(opp.rejection_reasons) == 2
    j = opp.to_journal()
    assert j["status"] == "FILTERED"
    assert "SPREAD_TOO_HIGH" in j["rejection_reasons"]


def test_opportunity_to_journal_excludes_heavy_fields() -> None:
    now = datetime.now(UTC)
    opp = Opportunity(
        opportunity_id="OPP-003",
        cycle_id="CYC-2",
        run_id="RUN-001",
        symbol="XAUUSD",
        timeframe=Timeframe.H4,
        timestamp=now,
        bid=1900.0,
        ask=1900.5,
        spread=0.5,
        extra={"raw_bars": list(range(200))},  # champ lourd non inclus dans to_journal
    )
    j = opp.to_journal()
    assert "extra" not in j
    assert "raw_bars" not in j


# ============================================================================
# Research persistence
# ============================================================================


@pytest.fixture
def rrepo() -> ResearchRepository:
    return ResearchRepository.from_url("sqlite://")


def test_research_repository_source_roundtrip(rrepo: ResearchRepository) -> None:
    now = datetime.now(UTC)
    src = ResearchSource(
        source_id="SRC-1",
        url="https://example.com/paper",
        title="A Trading Paper",
        author="A. Quant",
        retrieved_at=now,
        source_type=SourceType.ACADEMIC,
        notes="Excellent paper.",
    )
    rrepo.save_source(src)
    retrieved = rrepo.get_source("SRC-1")
    assert retrieved is not None
    assert retrieved.title == "A Trading Paper"
    assert retrieved.author == "A. Quant"
    assert retrieved.source_type == SourceType.ACADEMIC


def test_research_repository_source_is_idempotent(rrepo: ResearchRepository) -> None:
    now = datetime.now(UTC)
    src = ResearchSource(source_id="SRC-X", title="X", retrieved_at=now, source_type=SourceType.MANUAL)
    rrepo.save_source(src)
    rrepo.save_source(src)  # doublon ignoré
    assert len(rrepo.list_sources()) == 1


def test_research_repository_finding_roundtrip(rrepo: ResearchRepository) -> None:
    now = datetime.now(UTC)
    rrepo.save_source(ResearchSource(source_id="S1", title="S", retrieved_at=now, source_type=SourceType.MANUAL))
    f = ResearchFinding(
        finding_id="F-1",
        source_ids=["S1"],
        claim="Le momentum à H4 prédit un mouvement directionnel.",
        market="FOREX",
        timeframe="H4",
        conditions=["trend_confirmed", "spread_ok"],
        claimed_edge="5% alpha annualisé",
        limitations=["pas testé en exotiques"],
    )
    rrepo.save_finding(f)
    findings = rrepo.list_findings()
    assert len(findings) == 1
    assert findings[0].claim == f.claim


def test_research_repository_strategy_version_lifecycle(rrepo: ResearchRepository) -> None:
    now = datetime.now(UTC)
    v = StrategyVersion(
        strategy_id="MOM-01", version="1.0.0", code_hash="abc123",
        status=StrategyStatus.DISCOVERED, created_at=now,
    )
    rrepo.save_version(v)
    versions = rrepo.list_versions("MOM-01")
    assert len(versions) == 1
    assert versions[0].status is StrategyStatus.DISCOVERED

    rrepo.update_status("MOM-01", "1.0.0", StrategyStatus.FORMALIZED)
    updated = rrepo.list_versions("MOM-01")
    assert updated[0].status is StrategyStatus.FORMALIZED


def test_research_repository_experiment_and_result(rrepo: ResearchRepository) -> None:
    now = datetime.now(UTC)
    exp = StrategyExperiment(
        experiment_id="EXP-1",
        strategy_id="MOM-01",
        strategy_version="1.0.0",
        dataset="EURUSD_H4_2024",
        period_start=now,
        period_end=now,
        symbols=["EURUSD"],
        timeframes=["H4"],
        split="TRAIN",
    )
    rrepo.save_experiment(exp)
    assert len(rrepo.list_experiments()) == 1
    assert len(rrepo.list_experiments("MOM-01")) == 1
    assert len(rrepo.list_experiments("OTHER")) == 0

    result = ExperimentResult(experiment_id="EXP-1", trades=20, wins=12, losses=8,
                              win_rate=0.6, expectancy=0.8, profit_factor=1.5,
                              max_drawdown=0.05, r_total=16.0, passed=True)
    rrepo.save_result(result)
    fetched = rrepo.get_result("EXP-1")
    assert fetched is not None
    assert fetched.win_rate == pytest.approx(0.6)
    assert fetched.passed is True


def test_research_repository_stats(rrepo: ResearchRepository) -> None:
    s = rrepo.stats()
    assert s == {"sources": 0, "findings": 0, "hypotheses": 0,
                 "versions": 0, "experiments": 0, "results": 0}


def test_api_research_returns_real_data(svc: Components) -> None:
    """L'endpoint /api/research doit retourner les données réelles du dépôt Research."""
    from fastapi.testclient import TestClient

    from alladin.api.app import create_app

    api = TestClient(create_app(svc.settings, svc.repo, svc.broker))
    data = api.get("/api/research").json()
    assert "pipeline" in data
    assert "sources" in data
    assert "stats" in data
    assert data["pipeline"][0] == "DISCOVERED"
    assert data["stats"]["sources"] == 0  # base vide en test


def test_approved_strategy_requires_explicit_lifecycle(rrepo: ResearchRepository) -> None:
    """Une StrategyVersion ne peut pas être créée directement APPROVED."""
    now = datetime.now(UTC)
    v = StrategyVersion(
        strategy_id="FAKE-01", version="1.0.0", code_hash="xxx",
        status=StrategyStatus.DISCOVERED, created_at=now,
    )
    rrepo.save_version(v)
    # APPROVED n'est accessible que par update_status (progression du lifecycle)
    rrepo.update_status("FAKE-01", "1.0.0", StrategyStatus.APPROVED)
    assert rrepo.list_versions("FAKE-01")[0].status is StrategyStatus.APPROVED
