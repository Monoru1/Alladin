"""Bridge public spot data to the shared scanner. No exchange account or orders."""

from __future__ import annotations

import math
from datetime import datetime
from decimal import Decimal

from alladin.brokers.base import BrokerAdapter, BrokerCapabilities
from alladin.brokers.crypto import BinancePublicProvider, CryptoDataProvider, CryptoInstrument
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

    def __init__(
        self,
        provider: CryptoDataProvider,
        *,
        symbols: tuple[str, ...] | None = None,
        quote_assets: tuple[str, ...] = ("USDT", "USDC"),
        max_symbols: int | None = None,
        reference_currency: str = "USDT",
        reference_budget: float = 100_000.0,
        provenance: str = "crypto:mock",
    ) -> None:
        if symbols is not None and (not symbols or len(set(symbols)) != len(symbols)):
            raise ValueError("explicit symbols must be unique")
        if not reference_currency.strip() or not provenance.strip() or not quote_assets:
            raise ValueError("reference currency and provenance required")
        if max_symbols is not None and max_symbols < 1:
            raise ValueError("max_symbols must be positive")
        if not math.isfinite(reference_budget) or reference_budget <= 0:
            raise ValueError("reference budget must be positive")
        self.provider, self.symbols = provider, symbols
        self.quote_assets = frozenset(asset.upper() for asset in quote_assets)
        self.max_symbols = max_symbols
        self.reference_currency = reference_currency.upper()
        self.reference_budget, self.provenance = reference_budget, provenance
        self._catalog: dict[str, CryptoInstrument] | None = None

    def refresh_symbols(self) -> None:
        self._catalog = None

    def universe_summary(self) -> dict[str, object]:
        if isinstance(self.provider, BinancePublicProvider):
            report = self.provider.universe_report()
            return {
                "source": self.provenance,
                "total_discovered": report.total_discovered,
                "tradable": report.n_trade_eligible,
                "observe_only": len(report.observe_only),
                "ineligible": len(report.ineligible),
                "by_quote_asset": report.by_quote_asset,
                "selection_policy": "volume_24h+spread+exchange_constraints",
                "selection_limit": self.max_symbols,
            }
        catalog = self._instruments()
        return {
            "source": self.provenance,
            "total_discovered": len(catalog),
            "tradable": len(catalog),
            "observe_only": 0,
            "ineligible": 0,
            "by_quote_asset": {},
            "selection_policy": "fixture_catalog",
            "selection_limit": self.max_symbols,
        }

    def _instruments(self) -> dict[str, CryptoInstrument]:
        if self._catalog is not None:
            return self._catalog
        items = self.provider.instruments()
        selected = None if self.symbols is None else set(self.symbols)
        catalog = {
            item.symbol: item
            for item in items
            if item.quote_asset.upper() in self.quote_assets
            and (selected is None or item.symbol in selected)
        }
        if self.max_symbols is not None:
            if not isinstance(self.provider, BinancePublicProvider):
                items = sorted(catalog.values(), key=lambda item: item.symbol)[: self.max_symbols]
            else:
                items = self.provider.liquid_instruments(
                    list(catalog.values()), limit=self.max_symbols
                )
            catalog = {item.symbol: item for item in items}
        self._catalog = catalog
        return self._catalog

    def capabilities(self) -> BrokerCapabilities:
        return BrokerCapabilities(
            name=self.name,
            has_spread=False,
            has_close_time=True,
            has_real_volume=True,
            is_24_7=True,
            can_open_position=False,
            supported_asset_categories=frozenset({AssetCategory.CRYPTO_SPOT}),
            supported_timeframes=frozenset(
                {
                    Timeframe.M1,
                    Timeframe.M5,
                    Timeframe.M15,
                    Timeframe.M30,
                    Timeframe.H1,
                    Timeframe.H4,
                    Timeframe.D1,
                }
            ),
            max_bars=1000,
            provenance_tag=self.provenance,
        )

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def account_info(self) -> AccountSnapshot:
        # A reference budget is scanner input, never a real or DEMO exchange balance.
        return AccountSnapshot(
            login_masked="NO-ACCOUNT",
            server=self.provenance,
            currency=self.reference_currency,
            balance=self.reference_budget,
            equity=self.reference_budget,
            free_margin=0,
            margin=0,
            floating_pnl=0,
            leverage=0,
            account_type=AccountType.UNKNOWN,
            trade_allowed=False,
            timestamp=self.now(),
        )

    def now(self) -> datetime:
        return self.provider.now()

    def symbol_spec(self, symbol: str) -> InstrumentSpec | None:
        item = self._instruments().get(symbol)
        if item is None:
            return None  # no implicit conversion to scanner's reference currency
        return self._instrument_spec(item)

    def _instrument_spec(self, item: CryptoInstrument) -> InstrumentSpec | None:
        values = (item.tick_size, item.lot_size, item.min_qty, item.max_qty, item.min_notional)
        if not all(math.isfinite(v) and v > 0 for v in values) or item.min_qty > item.max_qty:
            return None
        exponent = Decimal(str(item.tick_size)).normalize().as_tuple().exponent
        assert isinstance(exponent, int)
        digits = max(0, -exponent)
        return InstrumentSpec(
            symbol=item.symbol,
            description="Spot public data — OBSERVE only",
            path="CRYPTO/SPOT",
            currency_base=item.base_asset,
            currency_profit=item.quote_asset,
            currency_margin=item.quote_asset,
            digits=digits,
            point=item.tick_size,
            trade_tick_size=item.tick_size,
            trade_tick_value=item.tick_size,
            trade_contract_size=1,
            volume_min=item.min_qty,
            volume_max=item.max_qty,
            volume_step=item.lot_size,
            category=AssetCategory.CRYPTO_SPOT,
            is_forex_like=False,
        )

    def list_symbols(self) -> list[InstrumentSpec]:
        return [s for item in self._instruments().values() if (s := self._instrument_spec(item)) is not None]

    def select_symbol(self, symbol: str) -> bool:
        return symbol in self._instruments()

    def tick(self, symbol: str) -> Tick | None:
        if symbol not in self._instruments():
            return None
        tick = self.provider.ticker(symbol)
        if tick is None or tick.symbol != symbol:
            return None
        if not all(math.isfinite(v) and v > 0 for v in (tick.bid, tick.ask)) or tick.ask <= tick.bid:
            return None
        return tick.to_tick()

    def bars(self, symbol: str, timeframe: Timeframe, count: int) -> list[Bar]:
        if symbol not in self._instruments():
            return []
        if timeframe not in self.capabilities().supported_timeframes or not 1 <= count <= 1000:
            raise ValueError("unsupported timeframe or count")
        now = self.now()
        return [
            b.model_copy(update={"provenance": self.provenance})
            for b in self.provider.klines(symbol, timeframe, count)
            if b.close_time is not None and b.close_time <= now and b.is_closed is True
        ]

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
