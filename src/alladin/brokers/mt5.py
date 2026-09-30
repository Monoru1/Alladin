"""MT5Broker : adapter MetaTrader 5 réel (package Python `MetaTrader5`).

- Le module MetaTrader5 est importé paresseusement (et injectable) : le CI et les tests n'ont besoin
  d'aucun terminal MT5.
- DEMO uniquement : le type de compte est lu sur le terminal (ACCOUNT_TRADE_MODE) ; tout autre
  résultat (réel, concours, inconnu, contradictoire) bloque l'exécution. Fail closed.
- Les identifiants éventuels (MT5_LOGIN/PASSWORD/SERVER) ne servent qu'à `initialize()`; ils ne sont
  jamais journalisés ni transmis aux agents.
"""

from __future__ import annotations

import importlib
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import SecretStr

from alladin.brokers import base as b
from alladin.core.enums import (
    AccountType,
    AssetCategory,
    CloseReason,
    DealEntry,
    EntryType,
    OrderAction,
    Side,
    SymbolTradeMode,
    Timeframe,
)
from alladin.core.errors import BrokerConnectionError, ExecutionBlockedError
from alladin.core.models import (
    AccountSnapshot,
    Bar,
    Deal,
    InstrumentSpec,
    OrderCheck,
    OrderRequest,
    OrderResult,
    PendingOrder,
    Position,
    Tick,
)
from alladin.market.universe import classify_symbol

_ERRORS = {
    -1: "échec générique",
    -2: "arguments invalides",
    -3: "mémoire insuffisante",
    -4: "aucune donnée",
    -5: "fonction interne indisponible",
    -6: "AUTORISATION REFUSÉE : le terminal MT5 n'est connecté à aucun compte de trading",
    -10001: "IPC : envoi impossible",
    -10002: "IPC : réception impossible",
    -10003: "initialisation IPC impossible : terminal MT5 introuvable ou non démarré",
    -10004: "IPC : pas de connexion au terminal",
    -10005: "délai dépassé en attendant le terminal (IPC)",
}
_TF = {"M1": "TIMEFRAME_M1", "M5": "TIMEFRAME_M5", "M15": "TIMEFRAME_M15", "M30": "TIMEFRAME_M30",
       "H1": "TIMEFRAME_H1", "H4": "TIMEFRAME_H4", "D1": "TIMEFRAME_D1"}  # fmt: skip
_SYMBOL_MODES = {0: SymbolTradeMode.DISABLED, 1: SymbolTradeMode.LONG_ONLY, 2: SymbolTradeMode.SHORT_ONLY,
                 3: SymbolTradeMode.CLOSE_ONLY, 4: SymbolTradeMode.FULL}  # fmt: skip
_ENTRY = {0: DealEntry.IN, 1: DealEntry.OUT, 2: DealEntry.INOUT, 3: DealEntry.OUT_BY}
_ORDER_TYPES = {0: "BUY", 1: "SELL", 2: "BUY_LIMIT", 3: "SELL_LIMIT", 4: "BUY_STOP", 5: "SELL_STOP",
                6: "BUY_STOP_LIMIT", 7: "SELL_STOP_LIMIT", 8: "CLOSE_BY"}  # fmt: skip


def explain_error(err: tuple[int, str] | Any) -> str:
    try:
        code, msg = int(err[0]), str(err[1])
    except (TypeError, IndexError, ValueError):
        return str(err)
    return f"{_ERRORS.get(code, msg)} (code {code}: {msg})"


class MT5Broker(b.BrokerAdapter):
    name = "MT5"

    def __init__(
        self,
        *,
        path: str | None = None,
        login: int | None = None,
        password: SecretStr | None = None,
        server: str | None = None,
        timeout_ms: int = 60000,
        server_utc_offset_hours: float | None = None,
        mt5_module: Any | None = None,
    ) -> None:
        self._path, self._login, self._password, self._server = path, login, password, server
        self._timeout = timeout_ms
        # None = détection automatique à la connexion (heure d'été/hiver incluse)
        self._offset_auto = server_utc_offset_hours is None
        self._offset = timedelta(hours=server_utc_offset_hours or 0.0)
        self.offset_source = "auto" if self._offset_auto else "config"
        self._mt5 = mt5_module
        self._connected = False

    # ------------------------------------------------------------------ infrastructure

    @property
    def mt5(self) -> Any:
        if self._mt5 is None:
            try:
                self._mt5 = importlib.import_module("MetaTrader5")
            except ImportError as exc:
                raise BrokerConnectionError(
                    "package Python 'MetaTrader5' introuvable (Windows uniquement) : pip install MetaTrader5"
                ) from exc
        return self._mt5

    def _to_utc(self, server_epoch: float) -> datetime:
        return datetime.fromtimestamp(server_epoch, UTC) - self._offset

    def _to_server_epoch(self, utc: datetime) -> int:
        return int((utc.astimezone(UTC) + self._offset).timestamp())

    def now(self) -> datetime:
        return datetime.now(UTC)

    def connect(self) -> None:
        mt5 = self.mt5
        kwargs: dict[str, Any] = {"timeout": self._timeout}
        if self._path:
            kwargs["path"] = self._path
        if self._login is not None:
            kwargs["login"] = self._login
            if self._password is not None:
                kwargs["password"] = self._password.get_secret_value()
            if self._server:
                kwargs["server"] = self._server
        if not mt5.initialize(**kwargs):
            raise BrokerConnectionError(explain_error(mt5.last_error()))
        self._connected = True
        ti = mt5.terminal_info()
        if ti is None or not ti.connected:
            self.disconnect()
            raise BrokerConnectionError(
                "terminal MT5 démarré mais NON connecté au serveur du broker (vérifier Internet / compte)"
            )
        if self._offset_auto:
            self._detect_server_offset()

    def _detect_server_offset(self) -> None:
        """Décalage heure-serveur/UTC déduit des ticks de plusieurs majeures (marché ouvert requis).

        Exige >= 3 symboles indépendants qui s'accordent (à 2 min d'un multiple de 30 min) : des ticks
        périmés (week-end) donneraient des valeurs incohérentes entre elles. Sinon : repli à 0 et
        `offset_source == "fallback"`, signalé par `mt5 status`.
        """
        found: list[int] = []
        for sym in ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD"):
            if not self.select_symbol(sym):
                continue
            t = self.mt5.symbol_info_tick(sym)
            if t is None:
                continue
            delta = float(t.time) - time.time()
            rounded = round(delta / 1800) * 1800
            if abs(delta - rounded) <= 120 and abs(rounded) <= 14 * 3600:
                found.append(int(rounded))
        if len(found) >= 3 and len(set(found)) == 1:
            self._offset = timedelta(seconds=found[0])
            self.offset_source = "auto"
        else:
            self._offset = timedelta(0)
            self.offset_source = "fallback"

    @property
    def server_utc_offset_hours(self) -> float:
        return self._offset.total_seconds() / 3600

    def disconnect(self) -> None:
        if self._mt5 is not None and self._connected:
            self._mt5.shutdown()
        self._connected = False

    def terminal_status(self) -> dict[str, Any]:
        ti = self.mt5.terminal_info()
        if ti is None:
            raise BrokerConnectionError("terminal_info indisponible")
        return {
            "connected": bool(ti.connected),
            "trade_allowed": bool(ti.trade_allowed),  # bouton « Algo Trading » du terminal
            "tradeapi_disabled": bool(getattr(ti, "tradeapi_disabled", False)),
            "build": int(ti.build),
            "company": str(ti.company),
            "name": str(ti.name),
            "path": str(ti.path),
        }

    # ------------------------------------------------------------------ compte

    def _account_type(self, info: Any) -> AccountType:
        mt5 = self.mt5
        try:
            mode = int(info.trade_mode)
            server = str(info.server or "")
            if int(info.login) <= 0 or not server:
                return AccountType.UNKNOWN
            if mode == int(mt5.ACCOUNT_TRADE_MODE_REAL):
                return AccountType.LIVE
            if mode == int(mt5.ACCOUNT_TRADE_MODE_DEMO):
                # contradiction nom de serveur / mode déclaré => on ne prend aucun risque
                if any(w in server.lower() for w in ("live", "real")):
                    return AccountType.UNKNOWN
                return AccountType.DEMO
            if mode == int(mt5.ACCOUNT_TRADE_MODE_CONTEST):
                return AccountType.CONTEST
        except (AttributeError, TypeError, ValueError):
            pass
        return AccountType.UNKNOWN

    def account_info(self) -> AccountSnapshot:
        mt5 = self.mt5
        ti = mt5.terminal_info()
        if ti is None or not ti.connected:
            raise BrokerConnectionError("terminal MT5 non connecté")
        a = mt5.account_info()
        if a is None:
            raise BrokerConnectionError(f"aucun compte de trading actif : {explain_error(mt5.last_error())}")
        login = str(a.login)
        return AccountSnapshot(
            login_masked="*" * max(0, len(login) - 3) + login[-3:],
            server=str(a.server),
            currency=str(a.currency),
            balance=float(a.balance),
            equity=float(a.equity),
            margin=float(a.margin),
            free_margin=float(a.margin_free),
            floating_pnl=float(a.profit),
            leverage=int(a.leverage),
            account_type=self._account_type(a),
            trade_allowed=bool(a.trade_allowed) and bool(ti.trade_allowed),
            timestamp=self.now(),
        )

    # ------------------------------------------------------------------ marché

    def _spec(self, i: Any) -> InstrumentSpec:
        spec = InstrumentSpec(
            symbol=str(i.name),
            description=str(i.description),
            path=str(i.path),
            currency_base=str(i.currency_base),
            currency_profit=str(i.currency_profit),
            currency_margin=str(i.currency_margin),
            digits=int(i.digits),
            point=float(i.point),
            trade_tick_size=float(i.trade_tick_size),
            trade_tick_value=float(i.trade_tick_value),
            trade_tick_value_loss=float(getattr(i, "trade_tick_value_loss", 0.0)),
            trade_contract_size=float(i.trade_contract_size),
            volume_min=float(i.volume_min),
            volume_max=float(i.volume_max),
            volume_step=float(i.volume_step),
            spread=float(i.spread),
            trade_mode=_SYMBOL_MODES.get(int(i.trade_mode), SymbolTradeMode.DISABLED),
            visible=bool(i.visible),
            stops_level=float(i.trade_stops_level),
            freeze_level=float(i.trade_freeze_level),
            is_forex_like=self._is_forex_calc(i),
        )
        spec.category = classify_symbol(spec) if spec.currency_base else AssetCategory.OTHER
        return spec

    def _is_forex_calc(self, info: Any) -> bool | None:
        mode = getattr(info, "trade_calc_mode", None)
        if mode is None:
            return None
        fx = {
            int(v)
            for n in ("SYMBOL_CALC_MODE_FOREX", "SYMBOL_CALC_MODE_FOREX_NO_LEVERAGE")
            if (v := getattr(self.mt5, n, None)) is not None
        }
        return int(mode) in fx if fx else None

    def list_symbols(self) -> list[InstrumentSpec]:
        infos = self.mt5.symbols_get()
        if infos is None:
            raise BrokerConnectionError(f"symbols_get a échoué : {explain_error(self.mt5.last_error())}")
        return [self._spec(i) for i in infos]

    def select_symbol(self, symbol: str) -> bool:
        info = self.mt5.symbol_info(symbol)
        if info is None:
            return False
        if info.visible:
            return True
        if not self.mt5.symbol_select(symbol, True):
            return False
        for _ in range(
            10
        ):  # le premier tick d'un symbole tout juste ajouté au Market Watch arrive en différé
            t = self.mt5.symbol_info_tick(symbol)
            if t is not None and t.bid > 0:
                break
            time.sleep(0.2)
        return True

    def symbol_spec(self, symbol: str) -> InstrumentSpec | None:
        """Spec fraîche ; sélectionne le symbole dans Market Watch si nécessaire (valeurs tick exactes)."""
        if not self.select_symbol(symbol):
            return None
        info = self.mt5.symbol_info(symbol)
        return self._spec(info) if info is not None else None

    def tick(self, symbol: str) -> Tick | None:
        t = self.mt5.symbol_info_tick(symbol)
        if t is None or t.bid <= 0 or t.ask <= 0:
            return None
        return Tick(symbol=symbol, time=self._to_utc(t.time), bid=float(t.bid), ask=float(t.ask))

    def bars(self, symbol: str, timeframe: Timeframe, count: int) -> list[Bar]:
        """Barres CLÔTURÉES uniquement (la barre en formation est retirée)."""
        rates = self.mt5.copy_rates_from_pos(symbol, getattr(self.mt5, _TF[timeframe.value]), 0, count + 1)
        if rates is None or len(rates) < 2:
            return []
        out = [
            Bar(
                time=self._to_utc(float(r["time"])),
                open=float(r["open"]),
                high=float(r["high"]),
                low=float(r["low"]),
                close=float(r["close"]),
                tick_volume=float(r["tick_volume"]),
                spread=float(r["spread"]),
            )
            for r in rates
        ]
        return out[:-1]

    # ------------------------------------------------------------------ positions / historique

    def positions(self) -> list[Position]:
        res = self.mt5.positions_get()
        if res is None:
            code = self.mt5.last_error()
            if int(code[0]) not in (1, 0):  # None + erreur => vraie erreur (sinon : aucune position)
                raise BrokerConnectionError(f"positions_get a échoué : {explain_error(code)}")
            return []
        return [
            Position(
                ticket=int(p.ticket),
                symbol=str(p.symbol),
                side=Side.BUY if int(p.type) == 0 else Side.SELL,
                volume=float(p.volume),
                price_open=float(p.price_open),
                sl=float(p.sl) or None,
                tp=float(p.tp) or None,
                price_current=float(p.price_current),
                profit=float(p.profit),
                swap=float(p.swap),
                commission=float(getattr(p, "commission", 0.0)),
                magic=int(p.magic),
                comment=str(p.comment),
                time_open=self._to_utc(p.time),
            )
            for p in res
        ]

    def orders(self) -> list[PendingOrder]:
        res = self.mt5.orders_get() or []
        out = []
        for o in res:
            name = _ORDER_TYPES.get(int(o.type), str(o.type))
            out.append(
                PendingOrder(
                    ticket=int(o.ticket),
                    symbol=str(o.symbol),
                    side=Side.BUY if name.startswith("BUY") else Side.SELL,
                    order_type=name,
                    volume=float(o.volume_current),
                    price=float(o.price_open),
                    sl=float(o.sl) or None,
                    tp=float(o.tp) or None,
                    magic=int(o.magic),
                    comment=str(o.comment),
                )
            )
        return out

    def _deal(self, d: Any) -> Deal | None:
        typ = int(d.type)
        if typ not in (0, 1):  # solde, crédit, etc. : ignorés
            return None
        reason = int(getattr(d, "reason", -1))
        close_reason = {4: CloseReason.SL, 5: CloseReason.TP, 6: CloseReason.STOP_OUT, 3: CloseReason.EXPERT,
                        0: CloseReason.MANUAL, 1: CloseReason.MANUAL, 2: CloseReason.MANUAL}.get(reason, CloseReason.UNKNOWN)  # fmt: skip
        return Deal(
            ticket=int(d.ticket),
            order=int(d.order),
            position_id=int(d.position_id),
            symbol=str(d.symbol),
            side=Side.BUY if typ == 0 else Side.SELL,
            entry=_ENTRY.get(int(d.entry), DealEntry.OTHER),
            volume=float(d.volume),
            price=float(d.price),
            profit=float(d.profit),
            commission=float(d.commission),
            swap=float(d.swap),
            fee=float(getattr(d, "fee", 0.0)),
            magic=int(d.magic),
            comment=str(d.comment),
            time=self._to_utc(d.time),
            close_reason=close_reason,
        )

    def history_deals(self, since: datetime, until: datetime) -> list[Deal]:
        # bornes en « epoch serveur » + marge d'un jour : évite toute ambiguïté de fuseau, on refiltre ensuite
        res = self.mt5.history_deals_get(
            self._to_server_epoch(since - timedelta(days=1)), self._to_server_epoch(until + timedelta(days=1))
        )
        if res is None:
            return []
        deals = [d for d in (self._deal(x) for x in res) if d is not None]
        return [d for d in deals if since <= d.time <= until]

    def calc_margin(self, symbol: str, side_buy: bool, volume: float, price: float) -> float | None:
        mt5 = self.mt5
        action = mt5.ORDER_TYPE_BUY if side_buy else mt5.ORDER_TYPE_SELL
        m = mt5.order_calc_margin(action, symbol, volume, price)
        return float(m) if m is not None else None

    # ------------------------------------------------------------------ exécution

    def _filling(self, symbol: str) -> int:
        mt5 = self.mt5
        info = mt5.symbol_info(symbol)
        flags = int(getattr(info, "filling_mode", 0)) if info is not None else 0
        if flags & 2:
            return int(mt5.ORDER_FILLING_IOC)
        if flags & 1:
            return int(mt5.ORDER_FILLING_FOK)
        return int(mt5.ORDER_FILLING_RETURN)

    def _build(self, req: OrderRequest) -> dict[str, Any]:
        mt5 = self.mt5
        info = mt5.symbol_info(req.symbol)
        if info is None:
            raise ExecutionBlockedError(f"symbole inconnu : {req.symbol}")
        digits = int(info.digits)
        tick = mt5.symbol_info_tick(req.symbol)
        if tick is None:
            raise ExecutionBlockedError(f"aucun tick pour {req.symbol}")
        d: dict[str, Any] = {
            "symbol": req.symbol, "volume": float(req.volume), "deviation": int(req.deviation_points),
            "magic": int(req.magic), "comment": req.comment, "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._filling(req.symbol),
        }  # fmt: skip
        if req.action is OrderAction.CLOSE:
            d.update(
                action=mt5.TRADE_ACTION_DEAL,
                position=int(req.position_ticket or 0),
                type=mt5.ORDER_TYPE_BUY if req.side is Side.BUY else mt5.ORDER_TYPE_SELL,
                price=float(tick.ask if req.side is Side.BUY else tick.bid),
            )
            return d
        if req.entry_type is EntryType.MARKET:
            d.update(
                action=mt5.TRADE_ACTION_DEAL,
                type=mt5.ORDER_TYPE_BUY if req.side is Side.BUY else mt5.ORDER_TYPE_SELL,
                price=float(tick.ask if req.side is Side.BUY else tick.bid),
            )
        else:
            kind = ("BUY" if req.side is Side.BUY else "SELL") + (
                "_LIMIT" if req.entry_type is EntryType.LIMIT else "_STOP"
            )
            d.update(
                action=mt5.TRADE_ACTION_PENDING,
                type=getattr(mt5, f"ORDER_TYPE_{kind}"),
                price=round(float(req.price or 0), digits),
            )
        if req.stop_loss is not None:
            d["sl"] = round(float(req.stop_loss), digits)
        if req.take_profit is not None:
            d["tp"] = round(float(req.take_profit), digits)
        return d

    def _retcode_name(self, code: int) -> str:
        for name in dir(self.mt5):
            if name.startswith("TRADE_RETCODE_") and getattr(self.mt5, name) == code:
                return name.removeprefix("TRADE_RETCODE_")
        return str(code)

    def check_order(self, request: OrderRequest) -> OrderCheck:
        try:
            payload = self._build(request)
        except ExecutionBlockedError as exc:
            return OrderCheck(ok=False, retcode=b.RETCODE_INVALID, message=str(exc))
        res = self.mt5.order_check(payload)
        if res is None:
            return OrderCheck(
                ok=False,
                retcode=-1,
                message=f"order_check sans réponse : {explain_error(self.mt5.last_error())}",
            )
        code = int(res.retcode)
        ok = code in (0, b.RETCODE_DONE)
        return OrderCheck(
            ok=ok,
            retcode=code,
            message=str(res.comment) if not ok else "",
            margin=float(res.margin),
            free_margin_after=float(res.margin_free),
        )

    def _send(self, request: OrderRequest) -> OrderResult:
        mt5 = self.mt5
        try:
            payload = self._build(request)
        except ExecutionBlockedError as exc:
            return OrderResult(
                accepted=False, retcode=b.RETCODE_BLOCKED, retcode_name="BLOCKED", message=str(exc)
            )
        res = mt5.order_send(payload)
        if res is None:
            return OrderResult(
                accepted=False,
                retcode=-1,
                retcode_name="NO_RESPONSE",
                message=explain_error(mt5.last_error()),
            )
        code = int(res.retcode)
        accepted = code in (b.RETCODE_DONE, b.RETCODE_DONE_PARTIAL, b.RETCODE_PLACED)
        name = self._retcode_name(code)
        if not accepted:
            return OrderResult(
                accepted=False,
                retcode=code,
                retcode_name=name,
                message=str(res.comment),
                requested_price=request.price,
                bid=float(res.bid) or None,
                ask=float(res.ask) or None,
            )
        executed_price = float(res.price) if float(res.price) > 0 else None
        commission, position_ticket = 0.0, int(res.order)
        if int(res.deal):
            deal = self._fetch_deal(int(res.deal))
            if deal is not None:
                position_ticket = deal.position_id or position_ticket
                commission = deal.commission + deal.fee
                executed_price = deal.price or executed_price
        tick = mt5.symbol_info_tick(request.symbol)
        bid, ask = (
            (float(tick.bid), float(tick.ask))
            if tick is not None
            else (float(res.bid) or None, float(res.ask) or None)
        )
        requested = request.price
        slippage = (executed_price - requested) * request.side.sign if executed_price and requested else None
        return OrderResult(
            accepted=True,
            retcode=code,
            retcode_name=name,
            message=str(res.comment),
            order=int(res.order),
            deal=int(res.deal),
            position_ticket=position_ticket,
            volume=float(res.volume),
            requested_price=requested,
            executed_price=executed_price,
            bid=bid,
            ask=ask,
            spread_at_fill=(ask - bid) if bid and ask else None,
            slippage=slippage,
            commission=commission,
            executed_at=self.now(),
        )

    def _fetch_deal(self, ticket: int) -> Deal | None:
        for _ in range(6):  # le deal peut mettre un instant à apparaître dans l'historique
            res = self.mt5.history_deals_get(ticket=ticket)
            if res:
                return self._deal(res[0])
            time.sleep(0.2)
        return None
