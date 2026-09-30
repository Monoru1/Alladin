"""Le VRAI MT5Broker, testé contre un faux module MetaTrader5 (aucun terminal requis)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from alladin.brokers.base import BrokerAdapter
from alladin.brokers.mt5 import MT5Broker
from alladin.core.approval import ApprovalToken, issue_close_token, issue_open_token
from alladin.core.enums import AccountType, AssetCategory, OrderAction, Side, Timeframe
from alladin.core.errors import BrokerConnectionError, ExecutionBlockedError
from alladin.core.models import OrderRequest
from tests.conftest import T0
from tests.fake_mt5 import FakeMT5


def make(fake: FakeMT5 | None = None, **kw: object) -> tuple[MT5Broker, FakeMT5]:
    fake = fake or FakeMT5(**kw)  # type: ignore[arg-type]
    b = MT5Broker(mt5_module=fake)
    b.connect()
    return b, fake


def open_req(volume: float = 0.1) -> OrderRequest:
    return OrderRequest(action=OrderAction.OPEN, symbol="EURUSD", side=Side.BUY, volume=volume, price=1.08506,
                        stop_loss=1.08306, take_profit=1.09006, magic=26000001, comment="ALLADIN|RUN-001|TREND-01")  # fmt: skip


def test_connection_failure_is_explicit_and_actionable() -> None:
    b = MT5Broker(mt5_module=FakeMT5(init_ok=False))
    with pytest.raises(BrokerConnectionError, match="aucun compte de trading"):
        b.connect()


def test_credentials_are_only_passed_to_initialize() -> None:
    from pydantic import SecretStr

    fake = FakeMT5()
    MT5Broker(mt5_module=fake, login=123, password=SecretStr("s3cr3t"), server="Acme-Demo").connect()
    assert fake.init_kwargs["login"] == 123 and fake.init_kwargs["password"] == "s3cr3t"


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"trade_mode": 0}, AccountType.DEMO),
        ({"trade_mode": 2, "server": "Acme-Live"}, AccountType.LIVE),
        ({"trade_mode": 1}, AccountType.CONTEST),
        ({"trade_mode": 9}, AccountType.UNKNOWN),
        ({"trade_mode": 0, "server": "Acme-Live01"}, AccountType.UNKNOWN),  # contradiction -> fail closed
        ({"trade_mode": 0, "login": 0}, AccountType.UNKNOWN),
        ({"trade_mode": 0, "server": ""}, AccountType.UNKNOWN),
    ],
)
def test_account_type_detection_fails_closed(kwargs: dict[str, object], expected: AccountType) -> None:
    b, _ = make(**kwargs)
    assert b.account_info().account_type is expected


def test_account_number_is_masked() -> None:
    b, _ = make()
    snap = b.account_info()
    assert snap.login_masked == "*****678" and "12345678" not in snap.model_dump_json()


def test_market_data_and_symbol_discovery() -> None:
    b, _ = make()
    specs = {s.symbol: s for s in b.list_symbols()}
    assert set(specs) == {"EURUSD", "GBPJPY", "US500USD"}
    assert specs["EURUSD"].category is AssetCategory.FOREX_MAJOR
    assert specs["GBPJPY"].category is AssetCategory.FOREX_JPY
    assert specs["US500USD"].category is AssetCategory.OTHER and not specs["US500USD"].is_tradable
    t = b.tick("EURUSD")
    assert t and t.ask > t.bid
    assert b.tick("NOPE") is None and b.symbol_spec("NOPE") is None


def test_bars_exclude_the_forming_bar() -> None:
    b, fake = make()
    bars = b.bars("EURUSD", Timeframe.H1, 5)
    assert len(bars) == 5
    assert fake.rates_requests[-1] == (
        "EURUSD",
        FakeMT5.TIMEFRAME_H1,
        0,
        6,
    )  # 5 + la barre en formation, retirée


def test_send_order_blocked_on_live_account_and_nothing_reaches_mt5() -> None:
    b, fake = make(trade_mode=2, server="Acme-Live")
    req = open_req()
    with pytest.raises(ExecutionBlockedError, match="LIVE ACCOUNT DETECTED — EXECUTION BLOCKED"):
        b.send_order(req, issue_open_token("RUN-001", "i1", "EURUSD", 0.1))
    assert fake.order_send_calls == []


def test_send_order_blocked_when_account_type_unreadable() -> None:
    b, fake = make()
    fake.account_none = True
    with pytest.raises(ExecutionBlockedError, match="ACCOUNT TYPE UNKNOWN — EXECUTION BLOCKED"):
        b.send_order(open_req(), issue_open_token("RUN-001", "i1", "EURUSD", 0.1))
    assert fake.order_send_calls == []


def test_send_order_requires_a_risk_engine_token() -> None:
    b, fake = make()
    with pytest.raises(ExecutionBlockedError, match="sans approbation"):
        b.send_order(open_req(), None)
    with pytest.raises(ExecutionBlockedError):
        ApprovalToken("OPEN", "RUN-001", "EURUSD", 0.1, T0)  # impossible de forger un jeton à la main
    assert fake.order_send_calls == []


def test_token_must_match_the_request() -> None:
    b, fake = make()
    with pytest.raises(ExecutionBlockedError, match="diffère"):
        b.send_order(open_req(volume=5.0), issue_open_token("RUN-001", "i1", "EURUSD", 0.1))  # volume gonflé
    with pytest.raises(ExecutionBlockedError, match="diffère"):
        b.send_order(open_req(), issue_open_token("RUN-001", "i1", "GBPJPY", 0.1))
    with pytest.raises(ExecutionBlockedError, match="incohérent"):
        b.send_order(open_req(), issue_close_token("RUN-001", "EURUSD", 0.1))
    assert fake.order_send_calls == []


def test_open_order_without_sl_is_refused_at_broker_level() -> None:
    b, fake = make()
    req = open_req().model_copy(update={"stop_loss": None})
    with pytest.raises(ExecutionBlockedError, match="NO SL"):
        b.send_order(req, issue_open_token("RUN-001", "i1", "EURUSD", 0.1))
    assert fake.order_send_calls == []


def test_stale_token_is_refused() -> None:
    from alladin.core.approval import verify_token

    tok = issue_open_token("RUN-001", "i1", "EURUSD", 0.1)
    with pytest.raises(ExecutionBlockedError, match="périmée"):
        verify_token(open_req(), tok, now=tok.issued_at + timedelta(minutes=5))


def test_demo_order_is_built_correctly_and_result_verified() -> None:
    b, fake = make()
    res = b.send_order(open_req(), issue_open_token("RUN-001", "i1", "EURUSD", 0.1))
    sent = fake.order_send_calls[0]
    assert sent["symbol"] == "EURUSD" and sent["volume"] == 0.1 and sent["type"] == FakeMT5.ORDER_TYPE_BUY
    assert sent["sl"] == 1.08306 and sent["tp"] == 1.09006
    assert sent["magic"] == 26000001 and sent["comment"] == "ALLADIN|RUN-001|TREND-01"
    assert (
        sent["type_filling"] == FakeMT5.ORDER_FILLING_IOC
    )  # choisi d'après le mode de remplissage du symbole
    assert res.accepted and res.retcode == 10009 and res.retcode_name == "DONE"
    assert res.deal and res.position_ticket and res.executed_price == 1.08506
    assert res.commission == pytest.approx(-0.35)
    assert [p.ticket for p in b.positions()] == [res.position_ticket]
    assert b.positions()[0].sl == 1.08306


def test_filling_mode_fallbacks() -> None:
    b, fake = make(filling_mode=1)  # FOK seul
    b.send_order(open_req(), issue_open_token("RUN-001", "i1", "EURUSD", 0.1))
    assert fake.order_send_calls[0]["type_filling"] == FakeMT5.ORDER_FILLING_FOK
    b2, fake2 = make(filling_mode=0)
    b2.send_order(open_req(), issue_open_token("RUN-001", "i1", "EURUSD", 0.1))
    assert fake2.order_send_calls[0]["type_filling"] == FakeMT5.ORDER_FILLING_RETURN


def test_rejected_order_is_not_reported_as_executed() -> None:
    b, fake = make(send_retcode=10019)
    res = b.send_order(open_req(), issue_open_token("RUN-001", "i1", "EURUSD", 0.1))
    assert not res.accepted and res.retcode == 10019 and res.retcode_name == "NO_MONEY"
    assert b.positions() == []


def test_close_position_goes_through_a_close_token() -> None:
    b, fake = make()
    opened = b.send_order(open_req(), issue_open_token("RUN-001", "i1", "EURUSD", 0.1))
    close = OrderRequest(action=OrderAction.CLOSE, symbol="EURUSD", side=Side.SELL, volume=0.1,
                         position_ticket=opened.position_ticket, magic=26000001)  # fmt: skip
    res = b.send_order(close, issue_close_token("RUN-001", "EURUSD", 0.1))
    assert res.accepted and fake.order_send_calls[1]["position"] == opened.position_ticket
    assert b.positions() == []


def test_history_deals_map_reasons_and_entries() -> None:
    b, _ = make()
    b.send_order(open_req(), issue_open_token("RUN-001", "i1", "EURUSD", 0.1))
    now = b.now()
    deals = b.history_deals(now - timedelta(hours=1), now + timedelta(hours=1))
    assert len(deals) == 1 and deals[0].entry.value == "IN" and deals[0].position_id


def test_precheck_uses_order_check() -> None:
    b, fake = make()
    chk = b.check_order(open_req())
    assert chk.ok and chk.margin == 1000.0 and fake.order_check_calls and not fake.order_send_calls


def test_mt5_broker_cannot_bypass_the_send_guard() -> None:
    """send_order (garde DEMO + jeton) est hérité tel quel : aucune surcharge dans MT5Broker."""
    assert MT5Broker.send_order is BrokerAdapter.send_order
    assert "send_order" not in vars(MT5Broker)
