"""Bridge public spot data to the shared scanner. No exchange account or orders."""
from __future__ import annotations

import math
from datetime import datetime
from decimal import Decimal

from alladin.brokers.base import BrokerAdapter, BrokerCapabilities
from alladin.brokers.crypto import CryptoDataProvider
from alladin.core.enums import AccountType, AssetCategory, Timeframe
from alladin.core.errors import ExecutionBlockedError
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


class CryptoObserveBroker(BrokerAdapter):
    name = "CRYPTO_PUBLIC_OBSERVE"

    def __init__(self, provider: CryptoDataProvider, *, symbols: tuple[str, ...] = ("BTCUSDT",),
                 reference_budget: float = 100_000.0, provenance: str = "crypto:mock") -> None:
        if not symbols or len(set(symbols)) != len(symbols) or not provenance.strip():
            raise ValueError("explicit unique symbols and provenance required")
        if not math.isfinite(reference_budget) or reference_budget <= 0:
            raise ValueError("reference budget must be positive")
        self.provider, self.symbols = provider, symbols
        self.reference_budget, self.provenance = reference_budget, provenance

    def capabilities(self) -> BrokerCapabilities:
        return BrokerCapabilities(name=self.name, has_spread=False, has_close_time=True,
                                  has_real_volume=True, is_24_7=True, can_open_position=False,
                                  supported_asset_categories=frozenset({AssetCategory.CRYPTO_SPOT}),
                                  supported_timeframes=frozenset({Timeframe.M1, Timeframe.M5, Timeframe.M15,
                                                                Timeframe.M30, Timeframe.H1, Timeframe.H4, Timeframe.D1}),
                                  max_bars=1000, provenance_tag=self.provenance)

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def account_info(self) -> AccountSnapshot:
        # A reference budget is scanner input, never a real or DEMO exchange balance.
        return AccountSnapshot(login_masked="NO-ACCOUNT", server=self.provenance, currency="USDT",
                               balance=self.reference_budget, equity=self.reference_budget,
                               free_margin=0, margin=0, floating_pnl=0, leverage=0,
                               account_type=AccountType.UNKNOWN, trade_allowed=False, timestamp=self.now())

    def now(self) -> datetime:
        return self.provider.now()

    def symbol_spec(self, symbol: str) -> InstrumentSpec | None:
        if symbol not in self.symbols:
            return None
        item = self.provider.instrument(symbol)
        if item is None or item.symbol != symbol or item.quote_asset != "USDT":
            return None  # no implicit conversion to scanner's reference currency
        values = (item.tick_size, item.lot_size, item.min_qty, item.max_qty, item.min_notional)
        if not all(math.isfinite(v) and v > 0 for v in values) or item.min_qty > item.max_qty:
            return None
        exponent = Decimal(str(item.tick_size)).normalize().as_tuple().exponent
        assert isinstance(exponent, int)
        digits = max(0, -exponent)
        return InstrumentSpec(symbol=symbol, description="Spot public data — OBSERVE only",
                              path="CRYPTO/SPOT", currency_base=item.base_asset, currency_profit=item.quote_asset,
                              currency_margin=item.quote_asset, digits=digits, point=item.tick_size,
                              trade_tick_size=item.tick_size, trade_tick_value=item.tick_size,
                              trade_contract_size=1, volume_min=item.min_qty, volume_max=item.max_qty,
                              volume_step=item.lot_size, category=AssetCategory.CRYPTO_SPOT, is_forex_like=False)

    def list_symbols(self) -> list[InstrumentSpec]:
        return [s for name in self.symbols if (s := self.symbol_spec(name)) is not None]

    def select_symbol(self, symbol: str) -> bool:
        return symbol in self.symbols

    def tick(self, symbol: str) -> Tick | None:
        if symbol not in self.symbols:
            return None
        tick = self.provider.ticker(symbol)
        if tick is None or tick.symbol != symbol:
            return None
        if not all(math.isfinite(v) and v > 0 for v in (tick.bid, tick.ask)) or tick.ask <= tick.bid:
            return None
        return tick.to_tick()

    def bars(self, symbol: str, timeframe: Timeframe, count: int) -> list[Bar]:
        if symbol not in self.symbols:
            return []
        if timeframe not in self.capabilities().supported_timeframes or not 1 <= count <= 1000:
            raise ValueError("unsupported timeframe or count")
        now = self.now()
        return [b.model_copy(update={"provenance": self.provenance}) for b in self.provider.klines(symbol, timeframe, count)
                if b.close_time is not None and b.close_time <= now and b.is_closed is True]

    def positions(self) -> list[Position]:
        return []

    def orders(self) -> list[PendingOrder]:
        return []

    def history_deals(self, since: datetime, until: datetime) -> list[Deal]:
        return []

    def calc_margin(self, symbol: str, side_buy: bool, volume: float, price: float) -> float | None:
        return None

    def check_order(self, request: OrderRequest) -> OrderCheck:
        raise ExecutionBlockedError("public data adapter: OBSERVE only")

    def _send(self, request: OrderRequest) -> OrderResult:
        raise ExecutionBlockedError("public data adapter: no order endpoint")
