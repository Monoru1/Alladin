"""Journal append-only, chaîne de hachage, NO TRADE, statistiques."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from alladin.journal.models import EventType
from alladin.journal.repository import JournalRepository
from alladin.orchestration.bootstrap import Components
from tests.conftest import make_intent


def test_journal_is_append_only(svc: Components) -> None:
    svc.journal.log(svc.run.run_id, EventType.INFO, {"x": 1})
    with svc.repo.engine.begin() as c, pytest.raises(DatabaseError, match="append-only"):
        c.execute(text("UPDATE journal_events SET payload='{}'"))
    with svc.repo.engine.begin() as c, pytest.raises(DatabaseError, match="append-only"):
        c.execute(text("DELETE FROM journal_events"))
    with svc.repo.engine.begin() as c, pytest.raises(DatabaseError, match="never deleted"):
        c.execute(text("DELETE FROM runs"))


def test_hash_chain_detects_tampering(tmp_path: Path) -> None:
    repo = JournalRepository.from_url(f"sqlite:///{tmp_path / 'j.db'}")
    for i in range(3):
        repo.append("RUN-X", "info", {"i": i})
    assert repo.verify_chain("RUN-X") == (True, "3 événements vérifiés")
    with repo.engine.begin() as c:  # un attaquant qui retire le trigger puis modifie une ligne
        c.execute(text("DROP TRIGGER journal_no_update"))
        c.execute(text("UPDATE journal_events SET payload=:p WHERE seq=2"), {"p": '{"i":99}'})
    ok, why = repo.verify_chain("RUN-X")
    assert not ok and "seq=2" in why


def test_events_are_sequenced_per_run(svc: Components) -> None:
    a = svc.journal.log("RUN-A", EventType.INFO, {})
    b = svc.journal.log("RUN-A", EventType.INFO, {})
    c = svc.journal.log("RUN-B", EventType.INFO, {})
    assert (a.seq, b.seq, c.seq) == (1, 2, 1) and b.hash != a.hash


def test_no_trade_is_fully_recorded(svc: Components) -> None:
    ev = svc.journal.no_trade(
        svc.run.run_id,
        studied=["EURUSD", "XAUUSD", "GBPJPY"],
        candidates=["GBPJPY"],
        strategies_evaluated={"GBPJPY": ["TREND-01"]},
        rejections={"XAUUSD": ["spread/ATR 0.40 > 0.15"], "EURUSD": ["régime UNKNOWN"]},
        agent="claude",
        reason="aucun setup de qualité aujourd'hui",
    )
    p = ev.payload
    assert ev.type == EventType.NO_TRADE and p["final_decision"] == "NO_TRADE"
    assert p["instruments_studied"] == ["EURUSD", "XAUUSD", "GBPJPY"] and p["agent_consulted"] == "claude"
    assert p["rejections"]["XAUUSD"] and p["strategies_evaluated"] == {"GBPJPY": ["TREND-01"]}
    assert svc.repo.events(svc.run.run_id, [EventType.NO_TRADE])


def test_runs_are_never_rewritten_a_new_run_gets_a_new_number(svc: Components, broker) -> None:  # type: ignore[no-untyped-def]
    broker.inject_pnl(-6_000)
    svc.monitor.sync()
    assert svc.repo.get_run("RUN-001").state == "FAILED"  # type: ignore[union-attr]
    second = svc.manager.create_run(svc.profile, broker_name="MOCK", account="x", initial_balance=94_000)
    assert second.run_id == "RUN-002" and second.magic == svc.run.magic + 1
    assert svc.repo.get_run("RUN-001").state == "FAILED"  # type: ignore[union-attr]


def test_stats_by_strategy_symbol_regime(svc: Components, broker) -> None:  # type: ignore[no-untyped-def]
    for sym, tp in (("EURUSD", True), ("GBPUSD", False)):
        r = svc.execution.submit(make_intent(svc, symbol=sym, risk_pct=1, strategy_id="TREND-01"))
        assert r.executed and r.decision
        lvl = r.decision.take_profit if tp else r.decision.stop_loss
        spread = 0.00015
        broker.set_price(sym, lvl + (0 if tp else -0.0001), (lvl + spread) if tp else lvl)  # type: ignore[operator]
        svc.monitor.sync()
    by = {s.key: s for s in svc.journal.stats("symbol", svc.run.run_id)}
    assert by["EURUSD"].wins == 1 and by["GBPUSD"].wins == 0
    (strat,) = svc.journal.stats("strategy")
    assert strat.key == "TREND-01@1.0.0" and strat.trades == 2
    assert svc.journal.stats("regime") and svc.journal.stats("session") and svc.journal.stats("agent")
