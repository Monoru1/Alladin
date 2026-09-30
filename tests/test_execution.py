"""ExecutionService + PositionMonitor : pipeline complet, identification, clôtures, réconciliation, MockBroker."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from alladin.brokers.mock import MockBroker
from alladin.core.approval import issue_open_token
from alladin.core.enums import AccountType, OrderAction, Side
from alladin.core.errors import ExecutionBlockedError
from alladin.core.models import OrderRequest, OrderResult
from alladin.execution.models import ExecStatus, make_comment, parse_comment, parse_intent
from alladin.journal.models import EventType
from alladin.orchestration.bootstrap import Components, build_services
from tests.conftest import make_intent


def hit(b: MockBroker, symbol: str, price: float, side: Side = Side.BUY) -> None:
    spread = 0.00012
    b.set_price(symbol, price, price + spread) if side is Side.BUY else b.set_price(
        symbol, price - spread, price
    )


def test_full_pipeline_open_then_tp(svc: Components, broker: MockBroker) -> None:
    res = svc.execution.submit(make_intent(svc, risk_pct=4))
    assert res.executed and res.order and res.order.retcode == 10009 and res.decision
    sent = broker.sent_orders[0]
    assert sent.volume == res.decision.volume == 2.0  # volume du PositionSizer, jamais de l'agent
    assert sent.stop_loss is not None and sent.take_profit is not None
    assert sent.magic == svc.run.magic and sent.comment == "ALLADIN|RUN-001|TREND-01"
    (trade,) = svc.repo.trades_for_run("RUN-001", "OPEN")
    assert (
        trade.ticket == res.position_ticket
        and trade.strategy_id == "TREND-01"
        and trade.strategy_version == "1.0.0"
    )
    assert (
        trade.risk_amount == pytest.approx(400, rel=1e-3) and trade.spread_at_entry and trade.entry_executed
    )

    hit(broker, "EURUSD", sent.take_profit + 0.00001)
    rep = svc.monitor.sync()
    assert rep.newly_closed == [trade.trade_id] and rep.open_positions == 0
    closed = svc.repo.get_trade(trade.trade_id)
    assert closed and closed.status == "CLOSED" and closed.close_reason == "TP"
    assert closed.net_pnl == pytest.approx(1000, rel=1e-2) and closed.r_multiple == pytest.approx(
        2.5, rel=1e-2
    )
    assert svc.run.watchdog.state.daily_closed_pnl and svc.run.watchdog.state.trading_days
    types = [e.type for e in svc.repo.events("RUN-001")]
    for t in (EventType.TRADE_INTENT, EventType.RISK_DECISION, EventType.ORDER_PRECHECK, EventType.ORDER_SENT,
              EventType.ORDER_RESULT, EventType.POSITION_OPENED, EventType.POSITION_CLOSED):  # fmt: skip
        assert t.value in types


def test_sl_hit_records_a_loss_of_minus_1r(svc: Components, broker: MockBroker) -> None:
    res = svc.execution.submit(make_intent(svc, risk_pct=4))
    assert res.executed and res.decision
    hit(broker, "EURUSD", res.decision.stop_loss - 0.00001)  # type: ignore[operator]
    svc.monitor.sync()
    t = svc.repo.get_trade(res.trade_id)  # type: ignore[arg-type]
    assert t and t.close_reason == "SL" and t.r_multiple == pytest.approx(-1.0, rel=1e-2)
    assert (
        t.mae <= 0
        and svc.repo.events("RUN-001", [EventType.POSITION_CLOSED])[0].payload["close_reason"] == "SL"
    )


def test_agent_cannot_smuggle_a_volume(svc: Components) -> None:
    raw = {"instrument": "EURUSD", "side": "BUY", "strategy_id": "TREND-01", "strategy_version": "1.0.0",
           "stop_loss": 1.08, "requested_risk_pct_of_working_capital": 2, "confidence": 0.5,
           "expires_at": "2099-01-01T00:00:00+00:00", "volume": 50}  # fmt: skip
    parsed = parse_intent(raw, run_id="RUN-001", agent="claude")
    assert parsed.intent is None and any("volume" in e for e in parsed.errors)
    with pytest.raises(ValidationError):
        make_intent(svc, volume=50)


def test_intent_schema_rejects_nan_and_naive_dates(svc: Components) -> None:
    with pytest.raises(ValidationError):
        make_intent(svc, stop_loss=float("nan"))
    with pytest.raises(ValidationError):
        make_intent(svc, expires_at=__import__("datetime").datetime(2030, 1, 1))
    with pytest.raises(ValidationError):
        make_intent(svc, requested_risk_pct_of_working_capital=0)


def test_broker_precheck_rejection_is_recorded_and_nothing_is_sent(
    svc: Components, broker: MockBroker, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alladin.core.models import OrderCheck

    monkeypatch.setattr(
        broker, "check_order", lambda r: OrderCheck(ok=False, retcode=10019, message="Not enough money")
    )
    res = svc.execution.submit(make_intent(svc))
    assert res.status is ExecStatus.REJECTED_BROKER and broker.sent_orders == []
    assert svc.repo.events("RUN-001", [EventType.ORDER_PRECHECK])[0].payload["check"]["ok"] is False
    assert svc.repo.trades_for_run("RUN-001") == []


def test_broker_rejection_after_send_is_not_treated_as_executed(
    svc: Components, broker: MockBroker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        broker,
        "_send",
        lambda r: OrderResult(
            accepted=False, retcode=10006, retcode_name="REJECT", message="Request rejected"
        ),
    )
    res = svc.execution.submit(make_intent(svc))
    assert res.status is ExecStatus.REJECTED_BROKER and "10006" in res.messages[0]
    assert svc.repo.trades_for_run("RUN-001") == []
    assert svc.repo.events("RUN-001", [EventType.ORDER_RESULT])[0].payload["accepted"] is False


def test_position_without_sl_is_closed_immediately(
    svc: Components, broker: MockBroker, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = broker._send

    def strip_sl(req: OrderRequest) -> OrderResult:
        return original(req.model_copy(update={"stop_loss": None}) if req.action is OrderAction.OPEN else req)

    monkeypatch.setattr(broker, "_send", strip_sl)
    res = svc.execution.submit(make_intent(svc))
    assert res.status is ExecStatus.FAILED and "SL absent" in res.messages[0]
    assert broker.positions() == []  # fermeture d'urgence


def test_send_without_risk_token_is_impossible(broker: MockBroker) -> None:
    req = OrderRequest(action=OrderAction.OPEN, symbol="EURUSD", side=Side.BUY, volume=1.0, stop_loss=1.0)
    with pytest.raises(ExecutionBlockedError):
        broker.send_order(req, None)
    with pytest.raises(ExecutionBlockedError):
        broker.send_order(
            req, issue_open_token("RUN-001", "x", "EURUSD", 2.0)
        )  # volume différent de celui approuvé
    assert broker.sent_orders == [] and broker.positions() == []


def test_only_alladin_positions_of_this_run_are_managed(svc: Components, broker: MockBroker) -> None:
    from alladin.core.approval import issue_open_token as tok

    foreign = OrderRequest(
        action=OrderAction.OPEN,
        symbol="GBPUSD",
        side=Side.BUY,
        volume=0.5,
        stop_loss=1.0,
        magic=0,
        comment="manual",
    )
    broker.send_order(foreign, tok("RUN-001", "m", "GBPUSD", 0.5))
    assert svc.execution.submit(make_intent(svc, risk_pct=1)).executed
    assert len(broker.positions()) == 2 and len(svc.execution.my_positions()) == 1
    assert svc.monitor.sync().foreign_ignored == 1
    assert svc.execution.close_all("test") == 1
    assert [p.symbol for p in broker.positions()] == ["GBPUSD"]  # la position manuelle est intacte
    assert not svc.execution.close_position(broker.positions()[0].ticket)


def test_comment_roundtrip() -> None:
    c = make_comment("RUN-001", "TREND-01")
    assert c == "ALLADIN|RUN-001|TREND-01" and parse_comment(c) == ("RUN-001", "TREND-01")
    assert parse_comment("manual") is None and len(make_comment("RUN-001", "X" * 50)) <= 31


def test_restart_reconciles_open_position_without_closing_it(settings, tmp_path) -> None:  # type: ignore[no-untyped-def]
    broker = MockBroker(balance=100_000.0)
    db = f"sqlite:///{tmp_path / 'restart.db'}"
    first = build_services(settings, broker, create_run=True, db_url=db)
    assert first is not None
    first.manager.start(first.run, broker.account_info())
    res = first.execution.submit(make_intent(first))
    assert res.executed

    # « redémarrage » : nouveaux objets, même base SQLite, même broker
    second = build_services(settings, broker, db_url=db)
    assert second is not None and second.run.run_id == first.run.run_id
    assert second.run.watchdog.run_state.value == "RUNNING"  # état restauré, pas perdu
    rep = second.monitor.reconcile()
    assert rep.open_positions == 1 and rep.adopted == [] and rep.newly_closed == []
    assert len(broker.positions()) == 1  # un redémarrage ne ferme JAMAIS rien
    assert len(second.repo.trades_for_run(second.run.run_id, "OPEN")) == 1


def test_orphan_alladin_position_is_adopted(svc: Components, broker: MockBroker) -> None:
    """Crash entre l'envoi et l'écriture en base : la position existe chez MT5 mais pas dans ALLADIN."""
    req = OrderRequest(action=OrderAction.OPEN, symbol="EURUSD", side=Side.BUY, volume=0.3, stop_loss=1.08,
                       magic=svc.run.magic, comment=make_comment(svc.run.run_id, "TREND-01"))  # fmt: skip
    opened = broker.send_order(req, issue_open_token(svc.run.run_id, "orph", "EURUSD", 0.3))
    assert svc.repo.trades_for_run(svc.run.run_id) == []
    rep = svc.monitor.reconcile()
    assert rep.adopted == [opened.position_ticket]
    (t,) = svc.repo.trades_for_run(svc.run.run_id, "OPEN")
    assert t.adopted and t.ticket == opened.position_ticket and t.strategy_id == "TREND-01"
    assert svc.repo.events(svc.run.run_id, [EventType.RECONCILE])


def test_position_closed_while_alladin_was_offline_is_finalised(svc: Components, broker: MockBroker) -> None:
    res = svc.execution.submit(make_intent(svc))
    assert res.executed and res.decision
    hit(broker, "EURUSD", res.decision.stop_loss - 0.00001)  # type: ignore[operator]  # SL touché hors-ligne
    rep = svc.monitor.reconcile()
    assert rep.newly_closed == [res.trade_id]
    assert svc.repo.get_trade(res.trade_id).close_reason == "SL"  # type: ignore[union-attr]


def test_sl_removed_on_open_position_raises_an_alert(svc: Components, broker: MockBroker) -> None:
    assert svc.execution.submit(make_intent(svc)).executed
    broker._positions[next(iter(broker._positions))].sl = None  # quelqu'un retire le SL dans le terminal
    rep = svc.monitor.sync()
    assert rep.sl_removed and svc.repo.events("RUN-001", [EventType.POSITION_UPDATE])


def test_mockbroker_basics() -> None:
    b = MockBroker(balance=10_000)
    acct = b.account_info()
    assert acct.account_type is AccountType.DEMO and acct.equity == 10_000 and acct.currency == "USD"
    specs = {s.symbol: s for s in b.list_symbols()}
    assert {"EURUSD", "GBPJPY", "XAUUSD"} <= set(specs) and specs["EURUSD"].trade_tick_value == pytest.approx(
        1.0
    )
    tick = b.tick("EURUSD")
    assert tick and tick.ask > tick.bid
    assert (
        len(b.bars("EURUSD", __import__("alladin.core.enums", fromlist=["Timeframe"]).Timeframe.H1, 50)) == 50
    )
    # margin & floating P&L
    req = OrderRequest(action=OrderAction.OPEN, symbol="EURUSD", side=Side.BUY, volume=1.0, stop_loss=1.0)
    res = b.send_order(req, issue_open_token("R", "i", "EURUSD", 1.0))
    assert res.accepted and b.account_info().margin == pytest.approx(1_085, rel=1e-3)
    b.set_price("EURUSD", 1.0950)
    assert b.account_info().floating_pnl == pytest.approx((1.0950 - res.executed_price) / 1e-5)  # type: ignore[operator]
    # marge insuffisante refusée par la pré-validation
    big = req.model_copy(update={"volume": 100.0})
    assert not b.check_order(big).ok
