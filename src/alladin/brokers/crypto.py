"""Crypto data adapter : fournit des donnees marche BTCUSDT sans contaminer le coeur MT5.

Architecture :
- CryptoDataProvider : abstraction pour fetcher klines/ticks
- BinanceTestnetProvider : implementation Binance Testnet ou market-data-only
- CryptoMockProvider : mock pour tests

Le BrokerAdapter principal (MT5) n'est PAS modifie.
Ce module fournit uniquement des donnees pour les experiences BTC.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from alladin.core.enums import Timeframe
from alladin.core.models import Bar, Tick

log = logging.getLogger(__name__)

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
        import random as _rng
        _rng.seed(self._seed)
        bars: list[Bar] = []
        tf_minutes = timeframe.minutes
        price = self._base_price
        t = self._time - timedelta(minutes=tf_minutes * count)
        for _ in range(count):
            change = _rng.gauss(0, price * 0.002)  # ~0.2% volatility per bar
            o = price
            c = price + change
            h = max(o, c) + abs(_rng.gauss(0, price * 0.001))
            low = min(o, c) - abs(_rng.gauss(0, price * 0.001))
            bars.append(Bar(
                time=t,
                close_time=t + timedelta(minutes=tf_minutes),
                is_closed=True,
                open=round(o, 2),
                high=round(h, 2),
                low=round(low, 2),
                close=round(c, 2),
                tick_volume=_rng.uniform(50, 500),
                spread=round(price * self._spread_bps / 10000, 2),
            ))
            price = c
            t += timedelta(minutes=tf_minutes)
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

    def instrument(self, symbol: str) -> CryptoInstrument:
        return CryptoInstrument(
            symbol=symbol,
            base_asset="BTC",
            quote_asset="USDT",
            tick_size=0.01,
            lot_size=0.00001,
            min_notional=10.0,
        )

    def now(self) -> datetime:
        return self._time

    def advance(self, seconds: float) -> None:
        self._time += timedelta(seconds=seconds)


class BinancePublicProvider(CryptoDataProvider):
    """Binance public market data (REST, no auth needed for klines/ticker).

    JAMAIS de credentials de production.
    Read-only : aucun ordre.
    """

    BASE_URL = "https://api.binance.com"
    TESTNET_URL = "https://testnet.binance.vision"

    def __init__(self, *, testnet: bool = True) -> None:
        self._base = self.TESTNET_URL if testnet else self.BASE_URL
        self._testnet = testnet

    def klines(self, symbol: str, timeframe: Timeframe, count: int) -> list[Bar]:
        import json
        import urllib.request

        interval = _TF_MAP.get(timeframe.value, "1h")
        url = f"{self._base}/api/v3/klines?symbol={symbol}&interval={interval}&limit={count}"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())
        except Exception:
            log.warning("Binance klines fetch failed for %s %s", symbol, timeframe.value)
            return []

        bars: list[Bar] = []
        decision_time = self.now()
        for k in data:
            # Binance closeTime est la derniere milliseconde de la bougie.
            # Une kline future ou en formation ne peut servir au signal.
            close_time = datetime.fromtimestamp((int(k[6]) + 1) / 1000, UTC)
            if close_time > decision_time:
                continue
            bars.append(Bar(
                time=datetime.fromtimestamp(k[0] / 1000, UTC),
                close_time=close_time,
                is_closed=True,
                open=float(k[1]),
                high=float(k[2]),
                low=float(k[3]),
                close=float(k[4]),
                tick_volume=float(k[5]),
                spread=0.0,
            ))
        return bars

    def ticker(self, symbol: str) -> CryptoTick | None:
        import json
        import urllib.request

        url = f"{self._base}/api/v3/ticker/bookTicker?symbol={symbol}"
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read())
        except Exception:
            log.warning("Binance ticker fetch failed for %s", symbol)
            return None

        bid = float(data.get("bidPrice", 0))
        ask = float(data.get("askPrice", 0))
        if bid <= 0 or ask <= 0:
            return None

        return CryptoTick(
            symbol=symbol,
            time=datetime.now(UTC),
            bid=bid,
            ask=ask,
            last=(bid + ask) / 2,
        )

    def instrument(self, symbol: str) -> CryptoInstrument | None:
        # Hardcoded pour BTCUSDT - evite un appel exchangeInfo a chaque fois
        if symbol == "BTCUSDT":
            return CryptoInstrument(
                symbol="BTCUSDT",
                base_asset="BTC",
                quote_asset="USDT",
                tick_size=0.01,
                lot_size=0.00001,
                min_notional=10.0,
            )
        return None

    def now(self) -> datetime:
        return datetime.now(UTC)
