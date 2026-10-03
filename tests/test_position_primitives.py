"""Lot F broker primitives: no terminal or order outside test doubles."""

from __future__ import annotations

import pytest

from alladin.brokers.mock import MockBroker
from alladin.core.approval import issue_open_token, issue_position_token, verify_token
from alladin.core.enums import OrderAction, Side
from alladin.core.errors import ExecutionBlockedError
from alladin.core.models import OrderRequest
from tests.test_mt5_broker import make, open_req


def management(req: OrderRequest, ticket: int, *, action: OrderAction = OrderAction.MODIFY) -> OrderRequest:
    return req.model_copy(update={"action": action, "position_ticket": ticket,
                                 "side": req.side.opposite if action is OrderAction.CLOSE else req.side})


@pytest.mark.parametrize("field,value", [("stop_loss", 1.084), ("take_profit", 1.095)])
def test_mt5_modify_preserves_other_protection(field: str, value: float) -> None:
    broker, fake = make()
    req = open_req()
    opened = broker.send_order(req, issue_open_token("RUN-001", "entry", req.symbol, req.volume))
    mod = management(req, opened.position_ticket).model_copy(
        update={"stop_loss": None, "take_profit": None, field: value})
    token = issue_position_token("RUN-001", "MODIFY", "proposal", mod.symbol, mod.volume, request=mod)
    assert broker.check_order(mod).ok
    result = broker.send_order(mod, token)
    assert result.accepted
    pos = broker.positions()[0]
    assert pos.ticket == opened.position_ticket and pos.volume == req.volume
    assert pos.sl == (value if field == "stop_loss" else req.stop_loss)
    assert pos.tp == (value if field == "take_profit" else req.take_profit)
    assert len(fake._deals) == 1  # modification is not a close or a new fill


@pytest.mark.parametrize("update", [{"position_ticket": 99999}, {"symbol": "GBPJPY"},
                                    {"magic": 2}, {"comment": "foreign"},
                                    {"stop_loss": None, "take_profit": None}])
def test_mt5_modify_rejects_invalid_identity_before_order_check(update: dict[str, object]) -> None:
    broker, fake = make()
    req = open_req()
    opened = broker.send_order(req, issue_open_token("RUN-001", "entry", req.symbol, req.volume))
    mod = management(req, opened.position_ticket).model_copy(update=update)
    assert not broker.check_order(mod).ok
    assert fake.order_check_calls == [] and len(fake.order_send_calls) == 1


def test_mt5_modify_fails_closed_when_position_read_fails() -> None:
    broker, fake = make()
    fake.positions_get = lambda **kw: None  # type: ignore[assignment]
    assert not broker.check_order(management(open_req(), 123)).ok
    assert fake.order_check_calls == []


@pytest.mark.parametrize("action", [OrderAction.MODIFY, OrderAction.CLOSE])
@pytest.mark.parametrize("update", [{"position_ticket": 2}, {"stop_loss": 1.08},
                                    {"take_profit": 1.1}, {"side": Side.SELL},
                                    {"magic": 42}, {"comment": "other"}, {"volume": 0.05}])
def test_position_token_binds_entire_request(action: OrderAction, update: dict[str, object]) -> None:
    req = management(open_req(), 1, action=action)
    # Ensure side mutation really changes CLOSE as well.
    if "side" in update:
        update = {"side": req.side.opposite}
    token = issue_position_token("RUN-001", action.value, "proposal", req.symbol, req.volume, request=req)  # type: ignore[arg-type]
    verify_token(req, token)
    with pytest.raises(ExecutionBlockedError):
        verify_token(req.model_copy(update=update), token)


@pytest.mark.parametrize("action", [OrderAction.CLOSE, OrderAction.MODIFY])
@pytest.mark.parametrize("update", [{"symbol": "GBPJPY"}, {"magic": 2}, {"comment": "foreign"}])
def test_mock_rejects_foreign_position_without_mutation(action: OrderAction, update: dict[str, object]) -> None:
    broker = MockBroker()
    req = open_req()
    opened = broker.send_order(req, issue_open_token("RUN-001", "entry", req.symbol, req.volume))
    mod = management(req, opened.position_ticket, action=action).model_copy(update=update)
    before = broker.positions()[0].model_dump()
    token = issue_position_token("RUN-001", action.value, "proposal", mod.symbol, mod.volume, request=mod)  # type: ignore[arg-type]
    assert not broker.send_order(mod, token).accepted
    assert broker.positions()[0].model_dump() == before


@pytest.mark.parametrize("volume", [0.0, -0.01, 0.005, 0.095, 0.11, float("nan"), float("inf")])
def test_mock_partial_close_rejects_invalid_volume(volume: float) -> None:
    broker = MockBroker()
    req = open_req()
    opened = broker.send_order(req, issue_open_token("RUN-001", "entry", req.symbol, req.volume))
    close = management(req, opened.position_ticket, action=OrderAction.CLOSE).model_copy(update={"volume": volume})
    assert not broker.check_order(close).ok
    assert broker.positions()[0].volume == req.volume


def test_mock_partial_close_preserves_residual_and_realizes_only_closed_volume() -> None:
    broker = MockBroker()
    req = open_req()
    opened = broker.send_order(req, issue_open_token("RUN-001", "entry", req.symbol, req.volume))
    initial = broker.account_info().balance
    close = management(req, opened.position_ticket, action=OrderAction.CLOSE).model_copy(update={"volume": 0.04})
    token = issue_position_token("RUN-001", "CLOSE", "proposal", close.symbol, close.volume, request=close)
    assert broker.send_order(close, token).accepted
    pos = broker.positions()[0]
    assert pos.ticket == opened.position_ticket and pos.volume == pytest.approx(0.06)
    assert pos.sl == req.stop_loss and pos.tp == req.take_profit
    deals = broker.history_deals(broker.now(), broker.now())
    closed = [d for d in deals if d.volume == 0.04]
    assert len(closed) == 1
    assert broker.account_info().balance - initial == pytest.approx(closed[0].net)
