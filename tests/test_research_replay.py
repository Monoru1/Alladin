from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import event, text

from alladin.core.enums import Timeframe
from alladin.core.models import Bar
from alladin.market.archive import ArchiveIncompleteError, MarketDataArchive
from alladin.orchestration.bootstrap import Components
from alladin.replay import ReplayContext
from alladin.research.models import (
    ExperimentResult,
    ResearchSource,
    SourceType,
    StrategyStatus,
    StrategyVersion,
)


def test_research_models_keep_sources_versions_and_safe_default_status() -> None:
    now = datetime.now(UTC)
    source = ResearchSource(source_id="SRC-1", title="Paper", retrieved_at=now, source_type=SourceType.ACADEMIC)
    version = StrategyVersion(strategy_id="TREND-X", version="1.0.0", source_ids=[source.source_id],
                              code_hash="abc123", created_at=now)
    assert version.status is StrategyStatus.DISCOVERED
    assert version.status is not StrategyStatus.APPROVED
    with pytest.raises(ValidationError):
        ExperimentResult(experiment_id="E-1", trades=2, wins=2, losses=1)


def test_replay_reconstructs_cycle_without_broker_side_effect(svc: Components, monkeypatch: pytest.MonkeyPatch) -> None:
    start = svc.broker.now() - timedelta(hours=3)
    bars = [Bar(time=start + timedelta(hours=i), open=1, high=2, low=0.5, close=1.5,
                available_at=start + timedelta(hours=i + 1), provenance="test") for i in range(2)]
    archive = MarketDataArchive(svc.repo.engine)
    archive.store("EURUSD", Timeframe.H1, bars, "CYC-REPLAY", decision_at=svc.broker.now())
    quarter = [Bar(time=start + timedelta(minutes=15 * i), open=2, high=3, low=1, close=2.5,
                   available_at=start + timedelta(minutes=15 * (i + 1)), provenance="test") for i in range(3)]
    archive.store("EURUSD", Timeframe.M15, quarter, "CYC-REPLAY", decision_at=svc.broker.now())
    svc.journal.current_cycle = "CYC-REPLAY"
    svc.journal.log(svc.run.run_id, "market.scan", {"analysed": 10})
    svc.journal.log(svc.run.run_id, "risk.decision", {"status": "APPROVED"})
    svc.journal.current_cycle = None
    before = list(svc.broker.positions())
    def forbidden_fetch(*_args: object, **_kwargs: object) -> list[Bar]:
        raise AssertionError("replay ne doit pas appeler le broker")
    monkeypatch.setattr(svc.broker, "bars", forbidden_fetch)
    statements: list[str] = []
    def record_sql(_conn: object, _cursor: object, statement: str, _parameters: object,
                   _context: object, _executemany: bool) -> None:
        statements.append(statement)
    event.listen(svc.repo.engine, "before_cursor_execute", record_sql)
    try:
        replay = ReplayContext.from_cycle(svc.repo, "CYC-REPLAY")
        assert ReplayContext.from_cycle(svc.repo, "CYC-REPLAY") == replay
    finally:
        event.remove(svc.repo.engine, "before_cursor_execute", record_sql)
    assert replay.run_id == svc.run.run_id
    assert [event["type"] for event in replay.events] == ["market.scan", "risk.decision"]
    assert replay.market_bars["EURUSD"][Timeframe.H1] == bars
    assert replay.market_bars["EURUSD"][Timeframe.M15] == quarter
    assert statements and all(s.lstrip().upper().startswith("SELECT") for s in statements)
    assert svc.broker.positions() == before


def test_replay_fails_without_an_archived_window(svc: Components) -> None:
    svc.journal.current_cycle = "CYC-NO-INPUT"
    svc.journal.log(svc.run.run_id, "market.scan", {"analysed": 0})
    svc.journal.current_cycle = None
    with pytest.raises(ArchiveIncompleteError, match="archive absente"):
        ReplayContext.from_cycle(svc.repo, "CYC-NO-INPUT")


def test_replay_fails_when_a_referenced_historical_bar_is_missing(svc: Components) -> None:
    MarketDataArchive(svc.repo.engine)
    stamp = int((svc.broker.now() - timedelta(hours=2)).timestamp())
    with svc.repo.engine.begin() as conn:
        conn.execute(text("INSERT INTO cycle_inputs (cycle_id,symbol,timeframe,n_bars,first_ts,last_ts,fingerprint,decision_at,workspace) VALUES (:cycle, 'EURUSD', 'H1', 1, :ts, :ts, :hash, :cutoff, 'ALLADIN')"),
                     {"cycle": "CYC-MISSING", "ts": stamp, "hash": "missing", "cutoff": svc.broker.now().isoformat()})
        conn.execute(text("INSERT INTO cycle_input_bars (cycle_id,symbol,timeframe,ts,workspace) VALUES ('CYC-MISSING', 'EURUSD', 'H1', :ts, 'ALLADIN')"), {"ts": stamp})
    svc.journal.current_cycle = "CYC-MISSING"
    svc.journal.log(svc.run.run_id, "market.scan", {"analysed": 1})
    svc.journal.current_cycle = None
    with pytest.raises(ArchiveIncompleteError, match="barres manquantes"):
        ReplayContext.from_cycle(svc.repo, "CYC-MISSING")
