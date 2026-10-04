"""Client REST Binance Spot commun aux donnees publiques et au compte read-only.

Le client n'expose volontairement aucune methode de creation, modification ou
annulation d'ordre. Les erreurs ambigues ne peuvent donc pas provoquer de retry
d'une commande de trading dans ce lot.
"""

from __future__ import annotations

import base64
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


class BinanceError(RuntimeError):
    """Erreur Binance explicite et sans donnees sensibles."""


class BinanceTransportError(BinanceError):
    pass


class BinanceResponseError(BinanceError):
    def __init__(self, message: str, *, status: int, code: int | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class BinanceClockError(BinanceResponseError):
    pass


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class BinanceTransport(Protocol):
    def request(self, method: str, url: str, headers: Mapping[str, str], timeout: float) -> HttpResponse: ...


class UrlLibBinanceTransport:
    def request(self, method: str, url: str, headers: Mapping[str, str], timeout: float) -> HttpResponse:
        request = urllib.request.Request(url, method=method, headers=dict(headers))
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return HttpResponse(response.status, dict(response.headers), response.read())
        except urllib.error.HTTPError as exc:
            return HttpResponse(exc.code, dict(exc.headers), exc.read())
        except (TimeoutError, urllib.error.URLError, OSError) as exc:
            raise BinanceTransportError(f"Binance network failure: {type(exc).__name__}") from exc


class PayloadSigner(Protocol):
    def __call__(self, payload: bytes) -> str: ...


class Ed25519PemSigner:
    """Charge une cle locale a la demande et ne conserve/logue jamais son contenu."""

    def __init__(self, private_key_path: Path) -> None:
        self.private_key_path = private_key_path

    def __call__(self, payload: bytes) -> str:
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.serialization import load_pem_private_key
        except ImportError as exc:  # pragma: no cover - dependance runtime declaree
            raise BinanceError("cryptography dependency unavailable") from exc
        try:
            key_data = self.private_key_path.read_bytes()
            key = load_pem_private_key(key_data, password=None)
            if not isinstance(key, Ed25519PrivateKey):
                raise ValueError("not an Ed25519 private key")
            signature = key.sign(payload)
        except (OSError, ValueError, TypeError) as exc:
            raise BinanceError("Binance Ed25519 private key unavailable or invalid") from exc
        return base64.b64encode(signature).decode("ascii")


class BinanceBalance(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    asset: str
    free: float = Field(ge=0, allow_inf_nan=False)
    locked: float = Field(ge=0, allow_inf_nan=False)

    @property
    def total(self) -> float:
        return self.free + self.locked


class BinanceAccount(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    observed_at: datetime
    can_trade: bool
    can_withdraw: bool
    can_deposit: bool
    permissions: tuple[str, ...]
    balances: tuple[BinanceBalance, ...]
    maker_commission_bps: float | None = None
    taker_commission_bps: float | None = None


class BinanceApiRestrictions(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    created_at: datetime
    ip_restricted: bool
    reading_enabled: bool
    withdrawals_enabled: bool
    spot_margin_trading_enabled: bool
    margin_enabled: bool
    futures_enabled: bool
    internal_transfer_enabled: bool
    universal_transfer_enabled: bool

    @property
    def safe_for_read_only(self) -> bool:
        return self.reading_enabled and not self.withdrawals_enabled and not self.spot_margin_trading_enabled


class BinanceOrder(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    symbol: str
    order_id: int
    client_order_id: str
    price: float = Field(ge=0, allow_inf_nan=False)
    original_quantity: float = Field(ge=0, allow_inf_nan=False)
    executed_quantity: float = Field(ge=0, allow_inf_nan=False)
    cumulative_quote_quantity: float = Field(ge=0, allow_inf_nan=False)
    status: str
    order_type: str
    side: str
    created_at: datetime
    updated_at: datetime


class BinanceTrade(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    symbol: str
    trade_id: int
    order_id: int
    price: float = Field(gt=0, allow_inf_nan=False)
    quantity: float = Field(gt=0, allow_inf_nan=False)
    quote_quantity: float = Field(ge=0, allow_inf_nan=False)
    commission: float = Field(ge=0, allow_inf_nan=False)
    commission_asset: str
    occurred_at: datetime
    is_buyer: bool
    is_maker: bool


class BinanceSymbolFilter(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")
    filter_type: str


class BinanceSymbolInfo(BaseModel):
    """Informations d'un symbole issues de GET /api/v3/exchangeInfo."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    symbol: str
    status: str             # "TRADING", "HALT", "BREAK", ...
    base_asset: str
    quote_asset: str
    is_spot_trading_allowed: bool
    order_types: tuple[str, ...]
    filters: tuple[BinanceSymbolFilter, ...]

    @property
    def is_trading(self) -> bool:
        return self.status == "TRADING"

    def get_filter(self, filter_type: str) -> BinanceSymbolFilter | None:
        for f in self.filters:
            if f.filter_type == filter_type:
                return f
        return None


class BinanceExchangeInfo(BaseModel):
    """Réponse parsée de GET /api/v3/exchangeInfo."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    server_time: datetime
    symbols: tuple[BinanceSymbolInfo, ...]

    def spot_symbols(self, quote_asset: str = "USDT") -> tuple[BinanceSymbolInfo, ...]:
        qa = quote_asset.upper()
        return tuple(s for s in self.symbols if s.quote_asset.upper() == qa and s.is_spot_trading_allowed)

    def trading_only(self) -> tuple[BinanceSymbolInfo, ...]:
        return tuple(s for s in self.symbols if s.is_trading)


def _parse_symbol_info(row: dict[str, object]) -> BinanceSymbolInfo:
    raw_filters = row.get("filters")
    filter_list: list[dict[str, object]] = [f for f in raw_filters if isinstance(f, dict)] if isinstance(raw_filters, list) else []
    filters = tuple(
        BinanceSymbolFilter(filter_type=str(f.get("filterType", "")), **{
            k: v for k, v in f.items() if k != "filterType"
        })
        for f in filter_list
    )
    raw_order_types = row.get("orderTypes")
    order_types_list: list[object] = list(raw_order_types) if isinstance(raw_order_types, list) else []
    order_types = tuple(str(t) for t in order_types_list if isinstance(t, str))
    return BinanceSymbolInfo(
        symbol=str(row["symbol"]),
        status=str(row.get("status", "")),
        base_asset=str(row.get("baseAsset", "")),
        quote_asset=str(row.get("quoteAsset", "")),
        is_spot_trading_allowed=bool(row.get("isSpotTradingAllowed", False)),
        order_types=order_types,
        filters=filters,
    )


def _timestamp(value: object) -> datetime:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("invalid Binance timestamp")
    return datetime.fromtimestamp(value / 1000, UTC)


def _finite_float(value: object, field: str) -> float:
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise BinanceResponseError(f"invalid Binance {field}", status=200) from exc
    if not math.isfinite(result):
        raise BinanceResponseError(f"invalid Binance {field}", status=200)
    return result


def _strict_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise BinanceResponseError(f"invalid Binance {field}", status=200)
    return value


class BinanceRestClient:
    MAINNET_URL = "https://api.binance.com"
    TESTNET_URL = "https://testnet.binance.vision"

    def __init__(
        self,
        *,
        testnet: bool = False,
        api_key: str | None = None,
        signer: PayloadSigner | None = None,
        transport: BinanceTransport | None = None,
        timeout: float = 10.0,
        max_attempts: int = 3,
        recv_window_ms: int = 5000,
        clock_ms: Callable[[], int] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if timeout <= 0 or not 1 <= max_attempts <= 5 or not 1 <= recv_window_ms <= 60_000:
            raise ValueError("invalid Binance client limits")
        if (api_key is None) != (signer is None):
            raise ValueError("api_key and signer must be configured together")
        self.base_url = self.TESTNET_URL if testnet else self.MAINNET_URL
        self.api_key = api_key
        self.signer = signer
        self.transport = transport or UrlLibBinanceTransport()
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.recv_window_ms = recv_window_ms
        self.clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self.sleep = sleep
        self._clock_offset_ms = 0

    def public(self, path: str, params: Mapping[str, object] | None = None) -> Any:
        return self._request(path, params or {}, signed=False)

    def signed(self, path: str, params: Mapping[str, object] | None = None) -> Any:
        if self.api_key is None or self.signer is None:
            raise BinanceError("Binance credentials not configured")
        try:
            return self._request(path, params or {}, signed=True)
        except BinanceClockError:
            self.sync_clock()
            return self._request(path, params or {}, signed=True)

    def sync_clock(self) -> int:
        before = self.clock_ms()
        payload = self.public("/api/v3/time")
        after = self.clock_ms()
        if not isinstance(payload, dict) or isinstance(payload.get("serverTime"), bool):
            raise BinanceResponseError("invalid Binance server time", status=200)
        try:
            server_time = int(payload["serverTime"])
        except (TypeError, ValueError) as exc:
            raise BinanceResponseError("invalid Binance server time", status=200) from exc
        self._clock_offset_ms = server_time - ((before + after) // 2)
        return self._clock_offset_ms

    def _request(self, path: str, params: Mapping[str, object], *, signed: bool) -> Any:
        if not path.startswith(("/api/", "/sapi/")):
            raise ValueError("Binance API path required")
        values = list(params.items())
        headers = {"Accept": "application/json", "User-Agent": "Alladin-Jafar/0.1"}
        if signed:
            assert self.api_key is not None and self.signer is not None
            values.extend(
                (("recvWindow", self.recv_window_ms), ("timestamp", self.clock_ms() + self._clock_offset_ms))
            )
            payload = urllib.parse.urlencode(values)
            values.append(("signature", self.signer(payload.encode("ascii"))))
            headers["X-MBX-APIKEY"] = self.api_key
        query = urllib.parse.urlencode(values)
        url = f"{self.base_url}{path}" + (f"?{query}" if query else "")
        for attempt in range(self.max_attempts):
            try:
                response = self.transport.request("GET", url, headers, self.timeout)
            except BinanceTransportError:
                if attempt + 1 >= self.max_attempts:
                    raise
                self.sleep(min(0.25 * (2**attempt), 2.0))
                continue
            if (response.status == 429 or 500 <= response.status < 600) and attempt + 1 < self.max_attempts:
                retry_after = response.headers.get("Retry-After", "0")
                try:
                    delay = max(float(retry_after), 0.25 * (2**attempt))
                except ValueError:
                    delay = 0.25 * (2**attempt)
                self.sleep(min(delay, 5.0))
                continue
            return self._decode(response)
        raise AssertionError("unreachable")

    @staticmethod
    def _decode(response: HttpResponse) -> Any:
        try:
            payload = json.loads(response.body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise BinanceResponseError("invalid Binance JSON response", status=response.status) from exc
        if not 200 <= response.status < 300:
            code = payload.get("code") if isinstance(payload, dict) else None
            code = code if isinstance(code, int) else None
            message = payload.get("msg") if isinstance(payload, dict) else None
            safe = message if isinstance(message, str) else "Binance request rejected"
            cls = BinanceClockError if code == -1021 else BinanceResponseError
            raise cls(safe, status=response.status, code=code)
        return payload

    def exchange_info(self, symbol: str | None = None) -> BinanceExchangeInfo:
        """GET /api/v3/exchangeInfo — endpoint public, pas de credentials requis."""
        params: dict[str, object] = {}
        if symbol is not None:
            params["symbol"] = symbol
        row = self.public("/api/v3/exchangeInfo", params)
        if not isinstance(row, dict):
            raise BinanceResponseError("invalid exchangeInfo response", status=200)
        raw_symbols = row.get("symbols")
        if not isinstance(raw_symbols, list):
            raise BinanceResponseError("invalid exchangeInfo symbols", status=200)
        try:
            symbols = tuple(
                _parse_symbol_info(s)
                for s in raw_symbols
                if isinstance(s, dict)
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise BinanceResponseError("invalid exchangeInfo symbol entry", status=200) from exc
        server_time = _timestamp(row.get("serverTime", 0))
        return BinanceExchangeInfo(server_time=server_time, symbols=symbols)

    def account(self) -> BinanceAccount:
        row = self.signed("/api/v3/account", {"omitZeroBalances": "false"})
        if not isinstance(row, dict) or not isinstance(row.get("balances"), list):
            raise BinanceResponseError("invalid Binance account response", status=200)
        if not all(isinstance(item, dict) for item in row["balances"]):
            raise BinanceResponseError("invalid Binance account balances", status=200)
        balances = tuple(
            BinanceBalance(
                asset=str(item["asset"]),
                free=_finite_float(item["free"], "balance"),
                locked=_finite_float(item["locked"], "balance"),
            )
            for item in row["balances"]
        )
        permissions = row.get("permissions", [])
        if not isinstance(permissions, list) or not all(isinstance(v, str) for v in permissions):
            raise BinanceResponseError("invalid Binance account permissions", status=200)
        maker = row.get("makerCommission")
        taker = row.get("takerCommission")
        return BinanceAccount(
            observed_at=datetime.now(UTC),
            can_trade=_strict_bool(row.get("canTrade"), "canTrade"),
            can_withdraw=_strict_bool(row.get("canWithdraw"), "canWithdraw"),
            can_deposit=_strict_bool(row.get("canDeposit"), "canDeposit"),
            permissions=tuple(permissions),
            balances=balances,
            maker_commission_bps=None if maker is None else _finite_float(maker, "maker commission"),
            taker_commission_bps=None if taker is None else _finite_float(taker, "taker commission"),
        )

    def api_restrictions(self) -> BinanceApiRestrictions:
        row = self.signed("/sapi/v1/account/apiRestrictions")
        if not isinstance(row, dict):
            raise BinanceResponseError("invalid Binance API restrictions", status=200)
        try:
            return BinanceApiRestrictions(
                created_at=_timestamp(row["createTime"]),
                ip_restricted=_strict_bool(row["ipRestrict"], "ipRestrict"),
                reading_enabled=_strict_bool(row["enableReading"], "enableReading"),
                withdrawals_enabled=_strict_bool(row["enableWithdrawals"], "enableWithdrawals"),
                spot_margin_trading_enabled=_strict_bool(
                    row["enableSpotAndMarginTrading"], "enableSpotAndMarginTrading"
                ),
                margin_enabled=_strict_bool(row["enableMargin"], "enableMargin"),
                futures_enabled=_strict_bool(row["enableFutures"], "enableFutures"),
                internal_transfer_enabled=_strict_bool(
                    row["enableInternalTransfer"], "enableInternalTransfer"
                ),
                universal_transfer_enabled=_strict_bool(
                    row["permitsUniversalTransfer"], "permitsUniversalTransfer"
                ),
            )
        except KeyError as exc:
            raise BinanceResponseError("invalid Binance API restrictions", status=200) from exc

    def open_orders(self, symbol: str | None = None) -> tuple[BinanceOrder, ...]:
        params: dict[str, object] = {} if symbol is None else {"symbol": symbol}
        return self._orders(self.signed("/api/v3/openOrders", params))

    def query_order(self, symbol: str, client_order_id: str) -> BinanceOrder | None:
        """Recherche idempotente avant toute decision de resoumission."""
        if not symbol or not client_order_id:
            raise ValueError("symbol and client_order_id required")
        try:
            row = self.signed(
                "/api/v3/order", {"symbol": symbol, "origClientOrderId": client_order_id}
            )
        except BinanceResponseError as exc:
            if exc.code == -2013:  # Order does not exist.
                return None
            raise
        orders = self._orders([row])
        return orders[0]

    def order_history(self, symbol: str, *, limit: int = 500) -> tuple[BinanceOrder, ...]:
        if not 1 <= limit <= 1000:
            raise ValueError("Binance order history limit out of range")
        return self._orders(self.signed("/api/v3/allOrders", {"symbol": symbol, "limit": limit}))

    def trade_history(self, symbol: str, *, limit: int = 500) -> tuple[BinanceTrade, ...]:
        if not 1 <= limit <= 1000:
            raise ValueError("Binance trade history limit out of range")
        rows = self.signed("/api/v3/myTrades", {"symbol": symbol, "limit": limit})
        if not isinstance(rows, list):
            raise BinanceResponseError("invalid Binance trade history", status=200)
        if not all(isinstance(r, dict) for r in rows):
            raise BinanceResponseError("invalid Binance trade history", status=200)
        try:
            return tuple(
                BinanceTrade(
                    symbol=str(r["symbol"]),
                    trade_id=int(r["id"]),
                    order_id=int(r["orderId"]),
                    price=_finite_float(r["price"], "trade price"),
                    quantity=_finite_float(r["qty"], "trade quantity"),
                    quote_quantity=_finite_float(r["quoteQty"], "trade quote quantity"),
                    commission=_finite_float(r["commission"], "trade commission"),
                    commission_asset=str(r["commissionAsset"]),
                    occurred_at=_timestamp(r["time"]),
                    is_buyer=_strict_bool(r["isBuyer"], "trade isBuyer"),
                    is_maker=_strict_bool(r["isMaker"], "trade isMaker"),
                )
                for r in rows
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise BinanceResponseError("invalid Binance trade history", status=200) from exc

    @staticmethod
    def _orders(rows: Any) -> tuple[BinanceOrder, ...]:
        if not isinstance(rows, list):
            raise BinanceResponseError("invalid Binance order response", status=200)
        if not all(isinstance(r, dict) for r in rows):
            raise BinanceResponseError("invalid Binance order response", status=200)
        try:
            return tuple(
                BinanceOrder(
                    symbol=str(r["symbol"]),
                    order_id=int(r["orderId"]),
                    client_order_id=str(r["clientOrderId"]),
                    price=_finite_float(r["price"], "order price"),
                    original_quantity=_finite_float(r["origQty"], "order quantity"),
                    executed_quantity=_finite_float(r["executedQty"], "executed quantity"),
                    cumulative_quote_quantity=_finite_float(r["cummulativeQuoteQty"], "quote quantity"),
                    status=str(r["status"]),
                    order_type=str(r["type"]),
                    side=str(r["side"]),
                    created_at=_timestamp(r["time"]),
                    updated_at=_timestamp(r["updateTime"]),
                )
                for r in rows
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise BinanceResponseError("invalid Binance order response", status=200) from exc
