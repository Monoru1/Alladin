"""Faux module `MetaTrader5` : permet de tester le VRAI MT5Broker sans terminal installé."""

from __future__ import annotations

import re
import time
from types import SimpleNamespace
from typing import Any


class FakeMT5:
    TIMEFRAME_M1, TIMEFRAME_M5, TIMEFRAME_M15, TIMEFRAME_M30 = 1, 5, 15, 30
    TIMEFRAME_H1, TIMEFRAME_H4, TIMEFRAME_D1 = 16385, 16388, 16408
    ACCOUNT_TRADE_MODE_DEMO, ACCOUNT_TRADE_MODE_CONTEST, ACCOUNT_TRADE_MODE_REAL = 0, 1, 2
    ORDER_TYPE_BUY, ORDER_TYPE_SELL, ORDER_TYPE_BUY_LIMIT, ORDER_TYPE_SELL_LIMIT = 0, 1, 2, 3
    ORDER_TYPE_BUY_STOP, ORDER_TYPE_SELL_STOP = 4, 5
    TRADE_ACTION_DEAL, TRADE_ACTION_PENDING = 1, 5
    ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 1, 2
    ORDER_TIME_GTC = 0
    TRADE_RETCODE_PLACED, TRADE_RETCODE_REJECT, TRADE_RETCODE_DONE, TRADE_RETCODE_DONE_PARTIAL = (
        10008,
        10006,
        10009,
        10010,
    )
    TRADE_RETCODE_NO_MONEY, TRADE_RETCODE_INVALID_STOPS = 10019, 10016

    def __init__(
        self,
        *,
        trade_mode: int = 0,
        server: str = "Acme-Demo",
        login: int = 12345678,
        init_ok: bool = True,
        init_error: tuple[int, str] = (-6, "Authorization failed"),
        balance: float = 50_000.0,
        filling_mode: int = 2,
        send_retcode: int = 10009,
        trade_allowed: bool = True,
    ) -> None:
        self.trade_mode, self.server, self.login = trade_mode, server, login
        self.init_ok, self._err = init_ok, init_error if not init_ok else (1, "Success")
        self.balance = balance
        self.filling_mode = filling_mode
        self.send_retcode = send_retcode
        self.trade_allowed = trade_allowed
        self.init_kwargs: dict[str, Any] = {}
        self.order_send_calls: list[dict[str, Any]] = []
        self.order_check_calls: list[dict[str, Any]] = []
        self.rates_requests: list[tuple[Any, ...]] = []
        self._positions: list[SimpleNamespace] = []
        self._deals: list[SimpleNamespace] = []
        self._next = 5000
        self.account_none = False
        self.prices = {"EURUSD": (1.08494, 1.08506), "GBPJPY": (190.488, 190.512)}

    # -- session
    def initialize(self, **kw: Any) -> bool:
        self.init_kwargs = kw
        return self.init_ok

    def shutdown(self) -> None: ...

    def last_error(self) -> tuple[int, str]:
        return self._err

    def terminal_info(self) -> SimpleNamespace:
        return SimpleNamespace(connected=True, trade_allowed=self.trade_allowed, tradeapi_disabled=False, build=5200,
                               company="Acme Markets", name="MetaTrader 5", path="C:/MT5")  # fmt: skip

    def account_info(self) -> SimpleNamespace | None:
        if self.account_none:
            return None
        return SimpleNamespace(login=self.login, trade_mode=self.trade_mode, leverage=100, balance=self.balance,
                               equity=self.balance, margin=0.0, margin_free=self.balance, profit=0.0,
                               currency="USD", server=self.server, trade_allowed=self.trade_allowed)  # fmt: skip

    # -- symboles
    def _info(self, name: str) -> SimpleNamespace:
        jpy = name.endswith("JPY")
        digits = 3 if jpy else 5
        return SimpleNamespace(
            name=name, description=name, path=f"Forex\\{name}", currency_base=name[:3], currency_profit=name[3:6],
            currency_margin=name[:3], digits=digits, point=10.0**-digits, trade_tick_size=10.0**-digits,
            trade_tick_value=0.67 if jpy else 1.0, trade_tick_value_loss=0.67 if jpy else 1.0,
            trade_contract_size=100000.0, volume_min=0.01, volume_max=50.0, volume_step=0.01, spread=12,
            trade_mode=4, visible=True, trade_stops_level=10, trade_freeze_level=0, filling_mode=self.filling_mode,
        )  # fmt: skip

    def symbols_get(self) -> tuple[SimpleNamespace, ...]:
        weird = self._info("US500USD")
        weird.currency_base, weird.trade_mode = "US500", 0
        return (self._info("EURUSD"), self._info("GBPJPY"), weird)

    def symbol_info(self, name: str) -> SimpleNamespace | None:
        return self._info(name) if name in self.prices else None

    def symbol_select(self, name: str, flag: bool) -> bool:
        return name in self.prices

    def symbol_info_tick(self, name: str) -> SimpleNamespace | None:
        if name not in self.prices:
            return None
        bid, ask = self.prices[name]
        return SimpleNamespace(time=int(time.time()), bid=bid, ask=ask)

    def copy_rates_from_pos(self, symbol: str, tf: int, start: int, count: int) -> list[dict[str, float]]:
        self.rates_requests.append((symbol, tf, start, count))
        t0 = int(time.time()) - count * 3600
        return [
            {"time": t0 + i * 3600, "open": 1.0 + i * 1e-4, "high": 1.001 + i * 1e-4, "low": 0.999 + i * 1e-4,
             "close": 1.0005 + i * 1e-4, "tick_volume": 100, "spread": 12, "real_volume": 0}
            for i in range(count)
        ]  # fmt: skip

    # -- positions / historique
    def positions_get(self, **_: Any) -> tuple[SimpleNamespace, ...]:
        return tuple(self._positions)

    def orders_get(self, **_: Any) -> tuple[()]:
        return ()

    def history_deals_get(
        self, *args: Any, ticket: int | None = None, **_: Any
    ) -> tuple[SimpleNamespace, ...]:
        if ticket is not None:
            return tuple(d for d in self._deals if d.ticket == ticket)
        return tuple(self._deals)

    def order_calc_margin(self, action: int, symbol: str, volume: float, price: float) -> float:
        return volume * 100000 / 100 * (1.0 if symbol != "GBPJPY" else 1.27)

    # -- ordres
    def order_check(self, req: dict[str, Any]) -> SimpleNamespace:
        self.order_check_calls.append(req)
        comment = req.get("comment", "")
        if len(comment) > 31 or re.fullmatch(r"[A-Za-z0-9_-]*", comment) is None:
            self._err = (-2, 'Invalid "comment" argument')
            return None  # type: ignore[return-value]
        return SimpleNamespace(retcode=0, comment="Done", margin=1000.0, margin_free=self.balance - 1000.0)

    def order_send(self, req: dict[str, Any]) -> SimpleNamespace:
        self.order_send_calls.append(req)
        bid, ask = self.prices[req["symbol"]]
        if self.send_retcode not in (10009, 10010, 10008):
            return SimpleNamespace(
                retcode=self.send_retcode,
                deal=0,
                order=0,
                volume=0.0,
                price=0.0,
                bid=bid,
                ask=ask,
                comment="Rejected",
            )
        self._next += 1
        ticket = self._next
        price = req["price"]
        if "position" in req:
            self._positions = [p for p in self._positions if p.ticket != req["position"]]
            entry, pos_id = 1, req["position"]
        else:
            self._positions.append(SimpleNamespace(
                ticket=ticket, symbol=req["symbol"], type=req["type"], volume=req["volume"], price_open=price,
                sl=req.get("sl", 0.0), tp=req.get("tp", 0.0), price_current=price, profit=0.0, swap=0.0,
                magic=req["magic"], comment=req["comment"], time=int(time.time()),
            ))  # fmt: skip
            entry, pos_id = 0, ticket
        self._next += 1
        self._deals.append(SimpleNamespace(
            ticket=self._next, order=ticket, time=int(time.time()), type=req["type"], entry=entry, magic=req["magic"],
            reason=3, position_id=pos_id, volume=req["volume"], price=price, commission=-3.5 * req["volume"],
            swap=0.0, profit=0.0, fee=0.0, symbol=req["symbol"], comment=req["comment"],
        ))  # fmt: skip
        return SimpleNamespace(retcode=self.send_retcode, deal=self._next, order=ticket, volume=req["volume"], price=price,
                               bid=bid, ask=ask, comment="Request executed")  # fmt: skip
