"""Crypto data adapter : fournit des donnees marche BTCUSDT sans contaminer le coeur MT5.

Architecture :
- CryptoDataProvider : abstraction pour fetcher klines/ticks
- BinanceTestnetProvider : implementation Binance Testnet ou market-data-only
- CryptoMockProvider : mock pour tests

Le BrokerAdapter principal (MT5) n'est PAS modifie.
Ce module fournit uniquement des donnees pour les experiences BTC.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from alladin.brokers.binance import BinanceError, BinanceRestClient
from alladin.core.enums import Timeframe
from alladin.core.models import Bar, Tick

# Mapping Timeframe -> Binance interval string
_TF_MAP: dict[str, str] = {
    "M1": "1m",
    "M5": "5m",
    "M15": "15m",
    "M30": "30m",
    "H1": "1h",
    "H4": "4h",
    "D1": "1d",
}


@dataclass
class CryptoTick:
    """Tick crypto minimal."""

    symbol: str
    time: datetime
    bid: float
    ask: float
    last: float
    volume_24h: float = 0.0

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    @property
    def spread_bps(self) -> float:
        """Spread en basis points."""
        mid = (self.ask + self.bid) / 2
        return (self.spread / mid * 10000) if mid > 0 else 0.0

    def to_tick(self) -> Tick:
        """Convertit en Tick standard Alladin."""
        return Tick(symbol=self.symbol, time=self.time, bid=self.bid, ask=self.ask)


@dataclass
class CryptoInstrument:
    """Spec instrument crypto."""

    symbol: str
    base_asset: str  # BTC
    quote_asset: str  # USDT
    tick_size: float = 0.01  # minimum price increment
    lot_size: float = 0.00001  # minimum qty increment
    min_notional: float = 10.0  # minimum order value
    min_qty: float = 0.00001
    max_qty: float = 1000.0
    market_lot_size: float | None = None
    market_min_qty: float | None = None
    market_max_qty: float | None = None
    order_types: tuple[str, ...] = ()


class CryptoDataProvider(ABC):
    """Abstraction pour les sources de donnees crypto."""

    @abstractmethod
    def klines(self, symbol: str, timeframe: Timeframe, count: int) -> list[Bar]:
        """Retourne uniquement les klines cloturees a now() (UTC)."""

    @abstractmethod
    def ticker(self, symbol: str) -> CryptoTick | None:
        """Retourne le dernier tick."""

    @abstractmethod
    def instrument(self, symbol: str) -> CryptoInstrument | None:
        """Retourne les specs de l'instrument."""

    @abstractmethod
    def instruments(self) -> list[CryptoInstrument]:
        """Decouvre les instruments spot eligibles exposes par la source."""

    @abstractmethod
    def now(self) -> datetime:
        """Heure serveur."""


class CryptoMockProvider(CryptoDataProvider):
    """Mock provider pour tests. Donnees deterministes."""

    def __init__(
        self,
        base_price: float = 65000.0,
        spread_bps: float = 5.0,
        seed: int = 42,
        start: datetime | None = None,
    ) -> None:
        self._base_price = base_price
        self._spread_bps = spread_bps
        self._time = start or datetime.now(UTC)
        self._seed = seed

    def klines(self, symbol: str, timeframe: Timeframe, count: int) -> list[Bar]:
        from random import Random

        if symbol != "BTCUSDT":
            return []
        bars: list[Bar] = []
        seconds = timeframe.minutes * 60
        end = int(self._time.timestamp()) // seconds
        for index in range(end - count, end):
            # Absolute identities survive changes in count, time and process.
            rng = Random(f"{self._seed}:{timeframe.value}:{index}")
            t = datetime.fromtimestamp(index * seconds, UTC)
            o = self._base_price * (1 + 0.02 * math.sin(index / 20) + 0.005 * math.sin(index / 3))
            c = o * (1 + rng.gauss(0, 0.002))
            h = max(o, c) + abs(rng.gauss(0, o * 0.001))
            low = min(o, c) - abs(rng.gauss(0, o * 0.001))
            bars.append(
                Bar(
                    time=t,
                    close_time=t + timedelta(seconds=seconds),
                    is_closed=True,
                    open=round(o, 2),
                    high=round(h, 2),
                    low=round(low, 2),
                    close=round(c, 2),
                    tick_volume=rng.uniform(50, 500),
                    spread=round(o * self._spread_bps / 10000, 2),
                )
            )
        return bars

    def ticker(self, symbol: str) -> CryptoTick:
        spread = self._base_price * self._spread_bps / 10000
        return CryptoTick(
            symbol=symbol,
            time=self._time,
            bid=round(self._base_price - spread / 2, 2),
            ask=round(self._base_price + spread / 2, 2),
            last=self._base_price,
            volume_24h=15000.0,
        )

    def instrument(self, symbol: str) -> CryptoInstrument | None:
        if symbol != "BTCUSDT":
            return None
        return CryptoInstrument(
            symbol=symbol,
            base_asset="BTC",
            quote_asset="USDT",
            tick_size=0.01,
            lot_size=0.00001,
            min_notional=10.0,
        )

    def instruments(self) -> list[CryptoInstrument]:
        item = self.instrument("BTCUSDT")
        return [] if item is None else [item]

    def now(self) -> datetime:
        return self._time

    def advance(self, seconds: float) -> None:
        self._time += timedelta(seconds=seconds)


class BinancePublicProvider(CryptoDataProvider):
    """Binance public market data (REST, no auth needed for klines/ticker).

    JAMAIS de credentials de production.
    Read-only : aucun ordre.
    """

    def __init__(self, *, testnet: bool = True, client: BinanceRestClient | None = None) -> None:
        self._testnet = testnet
        self.client = client or BinanceRestClient(testnet=testnet)

    def klines(self, symbol: str, timeframe: Timeframe, count: int) -> list[Bar]:
        interval = _TF_MAP.get(timeframe.value, "1h")
        try:
            data = self.client.public(
                "/api/v3/klines", {"symbol": symbol, "interval": interval, "limit": count}
            )
            if not isinstance(data, list):
                return []
        except BinanceError:
            return []

        bars: list[Bar] = []
        decision_time = self.now()
        for k in data:
            if not isinstance(k, list) or len(k) < 7:
                return []
            # Binance closeTime est la derniere milliseconde de la bougie.
            # Une kline future ou en formation ne peut servir au signal.
            close_time = datetime.fromtimestamp((int(k[6]) + 1) / 1000, UTC)
            if close_time > decision_time:
                continue
            bars.append(
                Bar(
                    time=datetime.fromtimestamp(k[0] / 1000, UTC),
                    close_time=close_time,
                    is_closed=True,
                    open=float(k[1]),
                    high=float(k[2]),
                    low=float(k[3]),
                    close=float(k[4]),
                    tick_volume=float(k[5]),
                    spread=0.0,
                )
            )
        return bars

    def ticker(self, symbol: str) -> CryptoTick | None:
        try:
            data = self.client.public("/api/v3/ticker/bookTicker", {"symbol": symbol})
        except BinanceError:
            return None
        if not isinstance(data, dict):
            return None
        try:
            bid, ask = float(data.get("bidPrice", 0)), float(data.get("askPrice", 0))
        except (TypeError, ValueError):
            return None
        if not all(math.isfinite(v) and v > 0 for v in (bid, ask)) or ask <= bid:
            return None

        return CryptoTick(
            symbol=symbol,
            time=datetime.now(UTC),
            bid=bid,
            ask=ask,
            last=(bid + ask) / 2,
        )

    def instrument(self, symbol: str) -> CryptoInstrument | None:
        try:
            data = self.client.public("/api/v3/exchangeInfo", {"symbol": symbol})
            if not isinstance(data, dict) or not isinstance(data.get("symbols"), list):
                return None
            row = next(
                (r for r in data["symbols"] if isinstance(r, dict) and r.get("symbol") == symbol), None
            )
            return self._parse_instrument(row)
        except (BinanceError, KeyError, TypeError, ValueError):
            return None

    def instruments(self) -> list[CryptoInstrument]:
        try:
            data = self.client.public("/api/v3/exchangeInfo")
            if not isinstance(data, dict) or not isinstance(data.get("symbols"), list):
                return []
            return [item for row in data["symbols"] if (item := self._parse_instrument(row)) is not None]
        except (BinanceError, KeyError, TypeError, ValueError):
            return []

    @staticmethod
    def _parse_instrument(row: Any) -> CryptoInstrument | None:
        if (
            not isinstance(row, dict)
            or row.get("status") != "TRADING"
            or not row.get("isSpotTradingAllowed", False)
        ):
            return None
        filters_raw = row.get("filters")
        if not isinstance(filters_raw, list):
            return None
        filters = {f["filterType"]: f for f in filters_raw if isinstance(f, dict) and "filterType" in f}
        tick = float(filters["PRICE_FILTER"]["tickSize"])
        lot = filters["LOT_SIZE"]
        step, low, high = (float(lot[k]) for k in ("stepSize", "minQty", "maxQty"))
        notional = filters.get("NOTIONAL", filters.get("MIN_NOTIONAL"))
        if notional is None:
            return None
        minimum = float(notional["minNotional"])
        values = (tick, step, low, high, minimum)
        if not all(math.isfinite(v) and v > 0 for v in values) or low > high:
            return None
        market = filters.get("MARKET_LOT_SIZE")
        market_values: tuple[float | None, float | None, float | None] = (None, None, None)
        if market is not None:
            market_values = tuple(float(market[k]) for k in ("stepSize", "minQty", "maxQty"))  # type: ignore[assignment]
            present = tuple(v for v in market_values if v is not None)
            if not all(math.isfinite(v) and v >= 0 for v in present):
                return None
        order_types = row.get("orderTypes", [])
        if not isinstance(order_types, list) or not all(isinstance(v, str) for v in order_types):
            return None
        return CryptoInstrument(
            symbol=str(row["symbol"]),
            base_asset=str(row["baseAsset"]),
            quote_asset=str(row["quoteAsset"]),
            tick_size=tick,
            lot_size=step,
            min_qty=low,
            max_qty=high,
            min_notional=minimum,
            market_lot_size=market_values[0],
            market_min_qty=market_values[1],
            market_max_qty=market_values[2],
            order_types=tuple(order_types),
        )

    def now(self) -> datetime:
        return datetime.now(UTC)
