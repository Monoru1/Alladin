"""MockBroker : broker en mémoire, déterministe, sans MetaTrader. Sert aux tests, à `demo` et au CI."""

from __future__ import annotations

import math
import random
from datetime import UTC, datetime, timedelta

from alladin.brokers import base as b
from alladin.core.enums import (
    AccountType,
    CloseReason,
    DealEntry,
    OrderAction,
    Side,
    SymbolTradeMode,
    Timeframe,
)
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

# symbole -> (prix initial, spread en points)
_DEFAULT_MARKET: dict[str, tuple[float, float]] = {
    "EURUSD": (1.0850, 12),
    "GBPUSD": (1.2700, 15),
    "USDJPY": (150.00, 14),
    "USDCHF": (0.8800, 16),
    "AUDUSD": (0.6600, 14),
    "USDCAD": (1.3600, 16),
    "NZDUSD": (0.6100, 18),
    "EURGBP": (0.8540, 16),
    "EURJPY": (162.75, 20),
    "GBPJPY": (190.50, 25),
    "AUDJPY": (99.00, 22),
    "EURCHF": (0.9550, 20),
    "EURAUD": (1.6440, 28),
    "GBPCAD": (1.7270, 30),
    "XAUUSD": (2350.00, 35),
    "USDTRY": (32.50, 600),
}
_CCY_PER_LOT = 100_000.0


class MockBroker(b.BrokerAdapter):
    name = "MOCK"

    def capabilities(self) -> b.BrokerCapabilities:
        return b.BrokerCapabilities(name="mock:test", has_spread=True, has_close_time=False)

    def __init__(
        self,
        balance: float = 100_000.0,
        *,
        account_type: AccountType = AccountType.DEMO,
        currency: str = "USD",
        leverage: int = 100,
        commission_per_lot: float = 0.0,
        slippage_points: float = 0.0,
        market: dict[str, tuple[float, float]] | None = None,
        seed: int = 7,
        start: datetime | None = None,
    ) -> None:
        self._balance = balance
        self._account_type = account_type
        self._currency = currency
        self._leverage = leverage
        self.commission_per_lot = commission_per_lot
        self.slippage_points = slippage_points
        self._seed = seed
        self._time = start or datetime.now(UTC)
        self._connected = False
        self._trade_allowed = True
        self._specs: dict[str, InstrumentSpec] = {}
        self._ticks: dict[str, Tick] = {}
        self._positions: dict[int, Position] = {}
        self._deals: list[Deal] = []
        self._next_ticket = 1000
        self.sent_orders: list[OrderRequest] = []  # pour assertions de tests
        for sym, (px, spr) in (market or _DEFAULT_MARKET).items():
            self._init_symbol(sym, px, spr)

    # ------------------------------------------------------------------ construction du marché

    def _init_symbol(self, sym: str, price: float, spread_pts: float) -> None:
        digits = 3 if sym.endswith("JPY") else (2 if sym.startswith("XAU") else (3 if price > 20 else 5))
        point = 10.0**-digits
        base, quote = sym[:3], sym[3:6]
        spec = InstrumentSpec(
            symbol=sym,
            description=f"{base} vs {quote}",
            path=f"Forex\\{sym}" if not sym.startswith("XAU") else f"Metals\\{sym}",
            currency_base=base,
            currency_profit=quote,
            currency_margin=base,
            digits=digits,
            point=point,
            trade_tick_size=point,
            trade_tick_value=0.0,  # recalculé dynamiquement
            trade_contract_size=100.0 if sym.startswith("XAU") else _CCY_PER_LOT,
            volume_min=0.01,
            volume_max=100.0,
            volume_step=0.01,
            spread=spread_pts,
            trade_mode=SymbolTradeMode.FULL,
            visible=True,
            stops_level=10,
        )
        spec.category = classify_symbol(spec)
        self._specs[sym] = spec
        half = spread_pts * point / 2
        self._ticks[sym] = Tick(
            symbol=sym, time=self._time, bid=round(price - half, digits), ask=round(price + half, digits)
        )
        self._refresh_tick_values()

    def _usd_per(self, ccy: str) -> float:
        """Valeur en devise du compte (USD) d'une unité de `ccy`."""
        if ccy == self._currency:
            return 1.0
        direct = self._ticks.get(f"{ccy}{self._currency}")
        if direct:
            return direct.mid
        inverse = self._ticks.get(f"{self._currency}{ccy}")
        if inverse:
            return 1.0 / inverse.mid
        return 1.0

    def _refresh_tick_values(self) -> None:
        for spec in self._specs.values():
            spec.trade_tick_value = (
                spec.trade_tick_size * spec.trade_contract_size * self._usd_per(spec.currency_profit)
            )

    # ------------------------------------------------------------------ horloge & prix (tests/démo)

    def now(self) -> datetime:
        return self._time

    def advance(self, delta: timedelta) -> None:
        self._time += delta
        for sym, t in list(self._ticks.items()):
            self._ticks[sym] = t.model_copy(update={"time": self._time})

    def set_price(self, symbol: str, bid: float, ask: float | None = None) -> None:
        """Fixe le prix d'un symbole puis déclenche les SL/TP touchés."""
        spec = self._specs[symbol]
        ask = ask if ask is not None else bid + spec.spread * spec.point
        self._ticks[symbol] = Tick(symbol=symbol, time=self._time, bid=bid, ask=ask)
        self._refresh_tick_values()
        for pos in list(self._positions.values()):
            if pos.symbol != symbol:
                continue
            tick = self._ticks[symbol]
            px = tick.bid if pos.side is Side.BUY else tick.ask
            pos.price_current = px
            hit_sl = pos.sl is not None and ((px <= pos.sl) if pos.side is Side.BUY else (px >= pos.sl))
            hit_tp = pos.tp is not None and ((px >= pos.tp) if pos.side is Side.BUY else (px <= pos.tp))
            if hit_sl:
                self._close(pos, pos.sl, CloseReason.SL)  # type: ignore[arg-type]
            elif hit_tp:
                self._close(pos, pos.tp, CloseReason.TP)  # type: ignore[arg-type]

    def inject_pnl(self, amount: float) -> None:
        """Modifie le solde (perte/gain externe simulé : frais, gap, dépôt). Réservé aux tests/démos."""
        self._balance += amount

    def set_account_type(self, account_type: AccountType) -> None:
        self._account_type = account_type

    # ------------------------------------------------------------------ connexion / compte

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def _floating(self, pos: Position) -> float:
        spec = self._specs[pos.symbol]
        tick = self._ticks[pos.symbol]
        px = tick.bid if pos.side is Side.BUY else tick.ask
        return (
            (px - pos.price_open) * pos.side.sign / spec.trade_tick_size * spec.trade_tick_value * pos.volume
        )

    def _margin_for(self, symbol: str, volume: float, _price: float) -> float:
        spec = self._specs[symbol]
        return volume * spec.trade_contract_size * self._usd_per(spec.currency_base) / self._leverage

    def account_info(self) -> AccountSnapshot:
        floating = sum(self._floating(p) for p in self._positions.values())
        equity = self._balance + floating
        margin = sum(self._margin_for(p.symbol, p.volume, p.price_open) for p in self._positions.values())
        return AccountSnapshot(
            login_masked="****MOCK",
            server="Mock-Server",
            currency=self._currency,
            balance=self._balance,
            equity=equity,
            margin=margin,
            free_margin=equity - margin,
            floating_pnl=floating,
            leverage=self._leverage,
            account_type=self._account_type,
            trade_allowed=self._trade_allowed,
            timestamp=self._time,
        )

    # ------------------------------------------------------------------ marché

    def list_symbols(self) -> list[InstrumentSpec]:
        return [s.model_copy() for s in self._specs.values()]

    def symbol_spec(self, symbol: str) -> InstrumentSpec | None:
        s = self._specs.get(symbol)
        return s.model_copy() if s else None

    def select_symbol(self, symbol: str) -> bool:
        return symbol in self._specs

    def tick(self, symbol: str) -> Tick | None:
        return self._ticks.get(symbol)

    def bars(self, symbol: str, timeframe: Timeframe, count: int) -> list[Bar]:
        """Marche aléatoire déterministe (seed) calée pour finir au prix courant."""
        spec = self._specs[symbol]
        tick = self._ticks[symbol]
        rnd = random.Random(f"{self._seed}-{symbol}-{timeframe.value}")
        vol = tick.mid * 0.0006 * math.sqrt(timeframe.minutes / 15)
        drift = rnd.uniform(-0.15, 0.15) * vol
        closes = [0.0] * count
        px = tick.mid
        # on construit à rebours puis on recale sur le prix courant
        series = [px]
        for _ in range(count - 1):
            px = px - (drift + rnd.gauss(0, vol))
            series.append(px)
        series.reverse()
        step = timedelta(minutes=timeframe.minutes)
        end = self._time.replace(second=0, microsecond=0)
        out: list[Bar] = []
        prev = series[0]
        for i, c in enumerate(series):
            o = prev
            hi = max(o, c) + abs(rnd.gauss(0, vol * 0.4))
            lo = min(o, c) - abs(rnd.gauss(0, vol * 0.4))
            closes[i] = c
            out.append(
                Bar(
                    time=end - step * (count - 1 - i),
                    open=round(o, spec.digits),
                    high=round(hi, spec.digits),
                    low=round(lo, spec.digits),
                    close=round(c, spec.digits),
                    tick_volume=float(rnd.randint(100, 2000)),
                    spread=spec.spread,
                )
            )
            prev = c
        return out

    # ------------------------------------------------------------------ positions / historique

    def positions(self) -> list[Position]:
        out = []
        for p in self._positions.values():
            q = p.model_copy()
            q.profit = self._floating(p)
            q.price_current = self._ticks[p.symbol].bid if p.side is Side.BUY else self._ticks[p.symbol].ask
            out.append(q)
        return out

    def orders(self) -> list[PendingOrder]:
        return []

    def history_deals(self, since: datetime, until: datetime) -> list[Deal]:
        return [d.model_copy() for d in self._deals if since <= d.time <= until]

    def calc_margin(self, symbol: str, side_buy: bool, volume: float, price: float) -> float | None:
        if symbol not in self._specs:
            return None
        return self._margin_for(symbol, volume, price)

    # ------------------------------------------------------------------ exécution

    def check_order(self, request: OrderRequest) -> OrderCheck:
        spec = self._specs.get(request.symbol)
        if spec is None:
            return OrderCheck(ok=False, retcode=b.RETCODE_INVALID, message="symbole inconnu")
        if request.action is OrderAction.CLOSE:
            ok = request.position_ticket in self._positions
            return OrderCheck(
                ok=ok, retcode=0 if ok else b.RETCODE_INVALID, message="" if ok else "position inconnue"
            )
        if not spec.is_tradable:
            return OrderCheck(
                ok=False, retcode=b.RETCODE_TRADE_DISABLED, message="trading désactivé sur le symbole"
            )
        v = request.volume
        steps = v / spec.volume_step
        if v < spec.volume_min or v > spec.volume_max or abs(steps - round(steps)) > 1e-6:
            return OrderCheck(ok=False, retcode=b.RETCODE_INVALID_VOLUME, message="volume invalide")
        tick = self._ticks[request.symbol]
        px = tick.ask if request.side is Side.BUY else tick.bid
        if request.stop_loss is not None:
            wrong = request.stop_loss >= px if request.side is Side.BUY else request.stop_loss <= px
            near = abs(px - request.stop_loss) < spec.stops_level * spec.point
            if wrong or near:
                return OrderCheck(ok=False, retcode=b.RETCODE_INVALID_STOPS, message="SL invalide")
        margin = self._margin_for(request.symbol, v, px)
        free = self.account_info().free_margin
        if margin > free:
            return OrderCheck(
                ok=False, retcode=b.RETCODE_NO_MONEY, message="marge insuffisante", margin=margin
            )
        return OrderCheck(ok=True, retcode=0, margin=margin, free_margin_after=free - margin)

    def _send(self, request: OrderRequest) -> OrderResult:
        self.sent_orders.append(request)
        chk = self.check_order(request)
        if not chk.ok:
            return OrderResult(
                accepted=False, retcode=chk.retcode, retcode_name="REJECTED", message=chk.message
            )
        tick = self._ticks[request.symbol]
        spec = self._specs[request.symbol]
        if request.action is OrderAction.CLOSE:
            pos = self._positions[request.position_ticket]  # type: ignore[index]
            px = tick.bid if pos.side is Side.BUY else tick.ask
            deal = self._close(pos, px, CloseReason.EXPERT)
            return OrderResult(
                accepted=True,
                retcode=b.RETCODE_DONE,
                retcode_name="DONE",
                order=deal.order,
                deal=deal.ticket,
                position_ticket=pos.ticket,
                volume=pos.volume,
                requested_price=request.price,
                executed_price=px,
                bid=tick.bid,
                ask=tick.ask,
                spread_at_fill=tick.spread,
                executed_at=self._time,
            )
        ref = tick.ask if request.side is Side.BUY else tick.bid
        slip = self.slippage_points * spec.point
        px = ref + slip if request.side is Side.BUY else ref - slip
        self._next_ticket += 1
        ticket = self._next_ticket
        pos = Position(
            ticket=ticket,
            symbol=request.symbol,
            side=request.side,
            volume=request.volume,
            price_open=px,
            sl=request.stop_loss,
            tp=request.take_profit,
            price_current=px,
            magic=request.magic,
            comment=request.comment,
            time_open=self._time,
            commission=-self.commission_per_lot * request.volume,
        )
        self._positions[ticket] = pos
        self._next_ticket += 1
        deal = Deal(
            ticket=self._next_ticket,
            order=ticket,
            position_id=ticket,
            symbol=request.symbol,
            side=request.side,
            entry=DealEntry.IN,
            volume=request.volume,
            price=px,
            commission=pos.commission,
            magic=request.magic,
            comment=request.comment,
            time=self._time,
        )
        self._deals.append(deal)
        self._balance += pos.commission  # commission débitée à l'ouverture
        requested = request.price if request.price is not None else ref
        slippage = (px - requested) * request.side.sign
        return OrderResult(
            accepted=True,
            retcode=b.RETCODE_DONE,
            retcode_name="DONE",
            order=ticket,
            deal=deal.ticket,
            position_ticket=ticket,
            volume=request.volume,
            requested_price=requested,
            executed_price=px,
            bid=tick.bid,
            ask=tick.ask,
            spread_at_fill=tick.spread,
            slippage=slippage,
            commission=pos.commission,
            executed_at=self._time,
        )

    def _close(self, pos: Position, price: float, reason: CloseReason) -> Deal:
        spec = self._specs[pos.symbol]
        pnl = (
            (price - pos.price_open)
            * pos.side.sign
            / spec.trade_tick_size
            * spec.trade_tick_value
            * pos.volume
        )
        self._balance += pnl
        self._next_ticket += 1
        deal = Deal(
            ticket=self._next_ticket,
            order=self._next_ticket,
            position_id=pos.ticket,
            symbol=pos.symbol,
            side=pos.side.opposite,
            entry=DealEntry.OUT,
            volume=pos.volume,
            price=price,
            profit=pnl,
            magic=pos.magic,
            comment=pos.comment,
            time=self._time,
            close_reason=reason,
        )
        self._deals.append(deal)
        del self._positions[pos.ticket]
        return deal
