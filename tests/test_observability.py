"""Observabilité : cycles, archive marché, migrations et séparation SYSTEM-TEST/RUN."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from alladin.agents.mock import MockAgent
from alladin.core.enums import Timeframe
from alladin.core.models import Bar
from alladin.execution.models import comment_matches, make_comment, parse_comment
from alladin.journal.models import EventType
from alladin.journal.repository import GENESIS, JournalRepository, _canon, _hash
from alladin.market.archive import ArchiveConflictError, ArchiveIncompleteError, MarketDataArchive
from alladin.orchestration.bootstrap import Components
from alladin.orchestration.state import RunManager
from alladin.research.models import StrategyStatus, StrategyVersion
from alladin.research.repository import ResearchRepository
from tests.conftest import T0


def test_cycle_id_is_propagated_to_the_complete_cycle_and_trade(svc: Components) -> None:
    research = ResearchRepository.from_engine(svc.repo.engine)
    for strategy_id in ("TREND-01", "BREAKOUT-01", "RANGE-01"):
        research.save_version(StrategyVersion(
            strategy_id=strategy_id, version="1.0.0", code_hash="test-hash",
            created_at=svc.broker.now(),
        ))
        for status in (StrategyStatus.FORMALIZED, StrategyStatus.BACKTESTING,
                       StrategyStatus.BACKTEST_PASSED, StrategyStatus.OOS_TESTING,
                       StrategyStatus.OOS_PASSED, StrategyStatus.DEMO_TESTING,
                       StrategyStatus.CANDIDATE, StrategyStatus.APPROVED):
            research.update_status(strategy_id, "1.0.0", status)
    outcome = svc.engine(MockAgent(), execute=True).run_cycle()
    assert outcome.decision == "TRADE", outcome.reason
    assert outcome.cycle_id
    events = svc.repo.events(svc.run.run_id, cycle_id=outcome.cycle_id)
    types = {event.type for event in events}
    assert {
        EventType.CYCLE_START.value,
        EventType.SCAN.value,
        EventType.STRATEGY_EVAL.value,
        EventType.AGENT_REQUEST.value,
        EventType.AGENT_RESPONSE.value,
        EventType.RISK_DECISION.value,
        EventType.ORDER_RESULT.value,
        EventType.POSITION_OPENED.value,
        EventType.CYCLE_END.value,
    } <= types
    assert all(event.cycle_id == outcome.cycle_id for event in events)
    assert svc.journal.current_cycle is None
    assert svc.repo.cycles(svc.run.run_id)[0]["cycle_id"] == outcome.cycle_id
    assert svc.repo.verify_chain(svc.run.run_id)[0]
    (trade,) = svc.repo.trades_for_run(svc.run.run_id, "OPEN")
    assert trade.cycle_id == outcome.cycle_id


def _bars(count: int = 3) -> list[Bar]:
    return [
        Bar(
            time=T0 + timedelta(hours=i),
            open=1 + i / 100,
            high=1.1 + i / 100,
            low=0.9 + i / 100,
            close=1.05 + i / 100,
            tick_volume=100 + i,
            spread=10,
        )
        for i in range(count)
    ]


def test_market_archive_is_incremental_deduplicated_and_immutable(svc: Components) -> None:
    archive = MarketDataArchive(svc.repo.engine)
    bars = _bars()
    decision = T0 + timedelta(hours=4)
    assert archive.store("EURUSD", Timeframe.H1, bars, "CYC-1", decision_at=decision) == 3
    assert archive.store("EURUSD", Timeframe.H1, bars, "CYC-2", decision_at=decision) == 0
    extra = bars[-1].model_copy(
        update={"time": bars[-1].time + timedelta(hours=1), "close": 1.2}
    )
    assert archive.store("EURUSD", Timeframe.H1, [*bars, extra], "CYC-3", decision_at=decision) == 1
    assert archive.load("EURUSD", Timeframe.H1) == [
        b.model_copy(update={"available_at": decision}) for b in [*bars, extra]
    ]
    assert archive.stats() == {"bars": 4, "symbols": 1}
    assert archive.cycle_inputs("CYC-2")[0]["n_bars"] == 3
    with pytest.raises(DatabaseError), svc.repo.engine.begin() as conn:
        conn.execute(text("UPDATE market_bars SET close=2 WHERE symbol='EURUSD'"))


def test_archive_late_insert_duplicates_fingerprint_and_restart(tmp_path: Path) -> None:
    path = tmp_path / "archive.db"
    repo = JournalRepository.from_url(f"sqlite:///{path}")
    archive = MarketDataArchive(repo.engine)
    source = _bars(4)
    # Le même instant peut être représenté avec un autre fuseau.
    source[0] = source[0].model_copy(update={
        "time": source[0].time.astimezone(timezone(timedelta(hours=2))),
        "close_time": source[0].time + timedelta(hours=1),
        "available_at": source[0].time + timedelta(hours=1, minutes=1),
        "provenance": "mt5:test", "is_closed": True,
    })
    assert archive.store("EURUSD", Timeframe.H1, [source[3], source[0], source[1]]) == 3
    before = archive.fingerprint("EURUSD", Timeframe.H1)
    assert archive.store("EURUSD", Timeframe.H1, [source[1], source[0]]) == 0
    assert archive.store("EURUSD", Timeframe.H1, [source[2]]) == 1
    assert archive._last_ts("EURUSD", Timeframe.H1.value) == int(source[3].time.timestamp())
    assert archive.load("EURUSD", Timeframe.H1) == source
    assert archive.fingerprint("EURUSD", Timeframe.H1) != before
    assert archive.fingerprint("EURUSD", Timeframe.H1) == archive.fingerprint(
        "EURUSD", Timeframe.H1, since=source[0].time, until=source[3].time)
    with pytest.raises(ArchiveConflictError, match="contradictoire"):
        archive.store("EURUSD", Timeframe.H1, [source[2].model_copy(update={"close": 99})])
    assert archive.stats()["bars"] == 4
    repo.engine.dispose()
    restarted = MarketDataArchive(JournalRepository.from_url(f"sqlite:///{path}").engine)
    assert restarted.load("EURUSD", Timeframe.H1) == source
    assert restarted._last_ts("EURUSD", Timeframe.H1.value) == int(source[3].time.timestamp())
    assert restarted.fingerprint("EURUSD", Timeframe.H1) == archive.fingerprint("EURUSD", Timeframe.H1)
    assert restarted.store("EURUSD", Timeframe.H1, source) == 0


def test_archive_batch_conflict_is_atomic_and_identical_rows_are_idempotent(svc: Components) -> None:
    archive = MarketDataArchive(svc.repo.engine)
    first = _bars(1)[0]
    with pytest.raises(ValueError, match="cutoff"):
        archive.store("EURUSD", Timeframe.H1, [first], "CYC-NO-CUTOFF")
    assert archive.store("EURUSD", Timeframe.H1, [first, first]) == 1
    assert archive.store("EURUSD", Timeframe.H1, [first, first]) == 0
    changed = first.model_copy(update={"spread": first.spread + 1})
    with pytest.raises(ArchiveConflictError, match="dans le lot"):
        archive.store("GBPUSD", Timeframe.H1, [first, changed])
    assert archive.load("GBPUSD", Timeframe.H1) == []
    with pytest.raises(ArchiveConflictError, match="archivée contradictoire"):
        archive.store("EURUSD", Timeframe.H1, [changed])
    assert archive.stats()["bars"] == 1


def test_archive_records_an_empty_cycle_timeframe(svc: Components) -> None:
    archive = MarketDataArchive(svc.repo.engine)
    assert archive.store("EURUSD", Timeframe.M15, [], "CYC-EMPTY", decision_at=T0) == 0
    assert archive.load_cycle("CYC-EMPTY") == {"EURUSD": {Timeframe.M15: []}}
    assert archive.store("EURUSD", Timeframe.M15, [], "CYC-EMPTY", decision_at=T0) == 0
    with pytest.raises(ArchiveConflictError, match="fenêtre de cycle"):
        archive.store("EURUSD", Timeframe.M15, _bars(1), "CYC-EMPTY", decision_at=T0 + timedelta(hours=1))


def test_scanner_decision_uses_the_exact_archived_bars(svc: Components) -> None:
    scanner = svc.engine(MockAgent()).scanner
    report = scanner.scan(cycle_id="CYC-SCAN-ARCHIVE")
    assert report.candidates
    archived = MarketDataArchive(svc.repo.engine).load_cycle("CYC-SCAN-ARCHIVE")
    for candidate in report.candidates:
        assert candidate.bars == archived[candidate.symbol]
        assert all(bar.available_at is not None for series in candidate.bars.values() for bar in series)


def test_archive_cycle_manifest_keeps_exact_historical_window_after_late_insert(svc: Components) -> None:
    archive = MarketDataArchive(svc.repo.engine)
    bars = _bars(4)
    decision = bars[-1].time + timedelta(hours=2)
    assert archive.store("EURUSD", Timeframe.H1, [bars[0], bars[1], bars[3]],
                         "CYC-GAP", decision_at=decision) == 3
    first = archive.load_cycle("CYC-GAP")["EURUSD"][Timeframe.H1]
    assert len(first) == 3
    assert [b.time for b in first] == [bars[i].time for i in (0, 1, 3)]
    assert all(b.available_at == decision for b in first)
    late = bars[2].model_copy(update={"available_at": decision - timedelta(minutes=1)})
    assert archive.store("EURUSD", Timeframe.H1, [late]) == 1
    assert archive.load_cycle("CYC-GAP")["EURUSD"][Timeframe.H1] == first
    assert archive.load("EURUSD", Timeframe.H1, available_until=decision - timedelta(seconds=1)) == [late]
    with pytest.raises(ArchiveConflictError, match="fenêtre de cycle"):
        archive.store("EURUSD", Timeframe.H1, bars, "CYC-GAP", decision_at=decision)
    with pytest.raises(ValueError, match="indisponible"):
        archive.store("EURUSD", Timeframe.H1, [bars[2].model_copy(update={
            "available_at": decision + timedelta(seconds=1)})], "CYC-FUTURE", decision_at=decision)
    with pytest.raises(ValueError, match="non clôturée"):
        archive.store("EURUSD", Timeframe.H1, [bars[3]], "CYC-EARLY",
                      decision_at=bars[3].time + timedelta(minutes=1))


def test_archive_migrates_existing_sqlite_and_legacy_window_fails_explicitly(tmp_path: Path) -> None:
    path = tmp_path / "legacy_archive.db"
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE market_bars (symbol VARCHAR, timeframe VARCHAR, ts INTEGER,
          open FLOAT NOT NULL, high FLOAT NOT NULL, low FLOAT NOT NULL, close FLOAT NOT NULL,
          tick_volume FLOAT NOT NULL, spread FLOAT NOT NULL,
          PRIMARY KEY (symbol, timeframe, ts));
        CREATE TABLE cycle_inputs (cycle_id VARCHAR, symbol VARCHAR, timeframe VARCHAR,
          n_bars INTEGER NOT NULL, first_ts INTEGER NOT NULL, last_ts INTEGER NOT NULL,
          PRIMARY KEY (cycle_id, symbol, timeframe));
    """)
    stamp = int(T0.timestamp())
    db.execute("INSERT INTO market_bars VALUES (?,?,?,?,?,?,?,?,?)",
               ("EURUSD", "H1", stamp, 1, 2, 0.5, 1.5, 100, 10))
    db.execute("INSERT INTO cycle_inputs VALUES (?,?,?,?,?,?)",
               ("OLD", "EURUSD", "H1", 1, stamp, stamp))
    db.commit()
    db.close()
    archive = MarketDataArchive(JournalRepository.from_url(f"sqlite:///{path}").engine)
    assert len(archive.load("EURUSD", Timeframe.H1)) == 1
    with pytest.raises(ArchiveIncompleteError, match="membres manquants"):
        archive.load_cycle("OLD")
    assert archive.store("EURUSD", Timeframe.H1, archive.load("EURUSD", Timeframe.H1)) == 0


def test_old_sqlite_database_is_migrated_without_breaking_hash_chain(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    ts = datetime(2026, 1, 1, tzinfo=UTC).isoformat()
    payload = _canon({"legacy": True})
    digest = _hash(GENESIS, "RUN-001", 1, ts, EventType.INFO.value, payload, None)
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE runs (run_id VARCHAR PRIMARY KEY, seq INTEGER UNIQUE NOT NULL,
          profile_id VARCHAR NOT NULL, state VARCHAR NOT NULL, phase INTEGER NOT NULL,
          initial_balance FLOAT NOT NULL, broker VARCHAR NOT NULL, account VARCHAR NOT NULL,
          magic INTEGER NOT NULL, created_at VARCHAR NOT NULL, updated_at VARCHAR NOT NULL,
          watchdog_state TEXT NOT NULL);
        CREATE TABLE journal_events (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id VARCHAR NOT NULL,
          seq INTEGER NOT NULL, ts VARCHAR NOT NULL, type VARCHAR NOT NULL, payload TEXT NOT NULL,
          prev_hash VARCHAR NOT NULL, hash VARCHAR NOT NULL);
        CREATE TABLE trades (trade_id VARCHAR PRIMARY KEY, run_id VARCHAR, symbol VARCHAR, side VARCHAR,
          strategy_id VARCHAR, strategy_version VARCHAR, regime VARCHAR, agent VARCHAR, status VARCHAR,
          ticket INTEGER, volume FLOAT, entry_requested FLOAT, entry_executed FLOAT, stop_loss FLOAT,
          take_profit FLOAT, risk_amount FLOAT, risk_pct_of_wc FLOAT, spread_at_entry FLOAT,
          slippage FLOAT, opened_at VARCHAR, closed_at VARCHAR, close_price FLOAT, close_reason VARCHAR,
          pnl_gross FLOAT, commission FLOAT, swap FLOAT, net_pnl FLOAT, r_multiple FLOAT, mae FLOAT,
          mfe FLOAT, equity_after FLOAT, adopted INTEGER);
        """
    )
    db.execute(
        "INSERT INTO journal_events(run_id,seq,ts,type,payload,prev_hash,hash) VALUES(?,?,?,?,?,?,?)",
        ("RUN-001", 1, ts, EventType.INFO.value, payload, GENESIS, digest),
    )
    db.commit()
    db.close()

    repo = JournalRepository.from_url(f"sqlite:///{path}")
    with repo.engine.connect() as conn:
        assert "kind" in {r[1] for r in conn.execute(text("PRAGMA table_info(runs)"))}
        assert "cycle_id" in {r[1] for r in conn.execute(text("PRAGMA table_info(journal_events)"))}
        assert "cycle_id" in {r[1] for r in conn.execute(text("PRAGMA table_info(trades)"))}
    assert repo.verify_chain("RUN-001") == (True, "1 événements vérifiés")


def test_system_test_numbering_and_magic_are_isolated(svc: Components) -> None:
    manager: RunManager = svc.manager
    account = svc.broker.account_info()
    system = manager.create_run(
        svc.profile,
        broker_name=svc.broker.name,
        account=account.login_masked,
        initial_balance=account.balance,
        kind="SYSTEM-TEST",
    )
    assert system.run_id == "SYSTEM-TEST-001"
    assert system.magic != svc.run.magic
    assert manager.latest_run_id(kind="RUN") == svc.run.run_id
    assert manager.latest_run_id(kind="SYSTEM-TEST") == system.run_id
    for record in svc.repo.list_runs():
        comment = make_comment(record.run_id, record.magic)
        assert parse_comment(comment) == (record.kind, record.magic)
        assert comment_matches(comment, record.run_id, record.magic)
