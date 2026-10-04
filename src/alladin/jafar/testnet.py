"""Adaptateur Binance Testnet pour Jafar — ordres sur testnet.binance.vision uniquement.

Séparation EXPLICITE et IRRÉVERSIBLE entre testnet et production :
- URL forcée vers testnet.binance.vision dans __init__ (jamais api.binance.com)
- Credentials distincts (BINANCE_TESTNET_API_KEY / BINANCE_TESTNET_PRIVATE_KEY_PATH)
- Network tag "TESTNET" gravé dans tous les résultats et logs
- Ne jamais instancier avec les credentials de production

Variables d'environnement attendues :
  BINANCE_TESTNET_API_KEY          — clé API testnet
  BINANCE_TESTNET_PRIVATE_KEY_PATH — chemin vers la clé Ed25519 testnet
  (distinctes de BINANCE_API_KEY et JAFAR_BINANCE_PRIVATE_KEY_PATH)

Si les credentials testnet sont absents :
  - les tests restent verts grâce aux mocks/fixtures
  - le runtime lève BinanceTestnetCredentialsMissing avec un message clair
  - aucun ordre production n'est envoyé
"""

from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from alladin.brokers.binance import (
    BinanceError,
    BinanceResponseError,
    BinanceRestClient,
    BinanceTransportError,
    Ed25519PemSigner,
    HttpResponse,
    PayloadSigner,
    _finite_float,
    _timestamp,
)

# ---------------------------------------------------------------------------
# Constantes réseau
# ---------------------------------------------------------------------------

_TESTNET_URL = "https://testnet.binance.vision"
_MAINNET_URL = "https://api.binance.com"


# ---------------------------------------------------------------------------
# Erreurs spécifiques testnet
# ---------------------------------------------------------------------------


class BinanceTestnetError(BinanceError):
    """Erreur spécifique au client testnet."""


class BinanceTestnetCredentialsMissing(BinanceTestnetError):
    """Credentials testnet absents. Configurer BINANCE_TESTNET_API_KEY et
    BINANCE_TESTNET_PRIVATE_KEY_PATH pour activer l'exécution testnet."""


# ---------------------------------------------------------------------------
# Modèles de résultats
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TnFill:
    price: float
    qty: float
    commission: float
    commission_asset: str


@dataclass(frozen=True)
class TnOrderResult:
    """Résultat d'un ordre soumis sur testnet."""

    symbol: str
    order_id: int
    client_order_id: str
    transact_time: datetime
    price: float
    original_qty: float
    executed_qty: float
    status: str
    side: str
    order_type: str
    fills: tuple[TnFill, ...]
    network: str = "TESTNET"  # toujours "TESTNET" — jamais modifiable

    @property
    def is_filled(self) -> bool:
        return self.status == "FILLED"

    @property
    def avg_fill_price(self) -> float | None:
        if not self.fills:
            return None
        total_qty = sum(f.qty for f in self.fills)
        if total_qty <= 0:
            return None
        return sum(f.price * f.qty for f in self.fills) / total_qty

    @property
    def total_commission(self) -> float:
        return sum(f.commission for f in self.fills)


@dataclass(frozen=True)
class TnCancelResult:
    symbol: str
    order_id: int
    client_order_id: str
    status: str
    orig_client_order_id: str
    network: str = "TESTNET"


# ---------------------------------------------------------------------------
# Transport étendu avec POST/DELETE
# ---------------------------------------------------------------------------


class TnHttpTransport:
    """Transport HTTP pour le client testnet. Supporte GET, POST, DELETE."""

    def request(self, method: str, url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
        req = urllib.request.Request(url, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return HttpResponse(resp.status, dict(resp.headers), resp.read())
        except urllib.error.HTTPError as exc:
            return HttpResponse(exc.code, dict(exc.headers), exc.read())
        except (TimeoutError, urllib.error.URLError, OSError) as exc:
            raise BinanceTransportError(f"Testnet network failure: {type(exc).__name__}") from exc

    def request_post(self, url: str, headers: dict[str, str], body: bytes, timeout: float) -> HttpResponse:
        req = urllib.request.Request(url, data=body, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return HttpResponse(resp.status, dict(resp.headers), resp.read())
        except urllib.error.HTTPError as exc:
            return HttpResponse(exc.code, dict(exc.headers), exc.read())
        except (TimeoutError, urllib.error.URLError, OSError) as exc:
            raise BinanceTransportError(f"Testnet POST failure: {type(exc).__name__}") from exc

    def request_delete(self, url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
        req = urllib.request.Request(url, method="DELETE", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return HttpResponse(resp.status, dict(resp.headers), resp.read())
        except urllib.error.HTTPError as exc:
            return HttpResponse(exc.code, dict(exc.headers), exc.read())
        except (TimeoutError, urllib.error.URLError, OSError) as exc:
            raise BinanceTransportError(f"Testnet DELETE failure: {type(exc).__name__}") from exc


# ---------------------------------------------------------------------------
# Client testnet avec ordres
# ---------------------------------------------------------------------------


class BinanceTestnetOrderClient:
    """Client Binance Testnet avec capacité d'envoi d'ordres.

    ARCHITECTURE DE SÉCURITÉ :
    - base_url est TOUJOURS _TESTNET_URL — défini dans __init__ et vérifié à chaque appel
    - Assertion de sécurité avant tout envoi (ne peut pas pointer vers mainnet)
    - Network tag "TESTNET" dans chaque résultat
    - Aucun credential de production accepté ici

    Pour les lectures (klines, ticker, account, open_orders, query_order),
    délègue au BinanceRestClient(testnet=True) interne.

    Pour les écritures (new_order, cancel_order), utilise des méthodes propres.
    """

    NETWORK_TAG = "TESTNET"

    def __init__(
        self,
        *,
        api_key: str,
        signer: PayloadSigner,
        transport: TnHttpTransport | None = None,
        timeout: float = 10.0,
        max_attempts: int = 3,
        recv_window_ms: int = 5000,
        clock_ms: Callable[[], int] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key:
            raise BinanceTestnetError("api_key obligatoire pour le client testnet")
        # URL hardcodée — jamais modifiable
        self._base_url = _TESTNET_URL
        self.api_key = api_key
        self.signer = signer
        self.transport = transport or TnHttpTransport()
        self.timeout = timeout
        self.max_attempts = max(1, min(max_attempts, 5))
        self.recv_window_ms = recv_window_ms
        self.clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self.sleep = sleep
        self._clock_offset_ms = 0

        # Client read-only pour les GETs (délégation propre)
        self._read_client = BinanceRestClient(
            testnet=True,
            api_key=api_key,
            signer=signer,
            timeout=timeout,
            max_attempts=max_attempts,
            recv_window_ms=recv_window_ms,
            clock_ms=clock_ms,
            sleep=sleep,
        )
        # Vérification finale
        assert self._base_url == _TESTNET_URL, "BUG: base_url pointe vers production"
        assert _MAINNET_URL not in self._base_url, "BUG: URL production détectée"

    # ------------------------------------------------------------------ sécurité

    def _guard(self) -> None:
        """Assertion de sécurité avant tout envoi d'ordre."""
        if self._base_url != _TESTNET_URL or _MAINNET_URL in self._base_url:
            raise BinanceTestnetError("SÉCURITÉ: base_url invalide — ordre bloqué")

    # ------------------------------------------------------------------ délégation GETs

    def query_order(self, symbol: str, client_order_id: str) -> Any:
        return self._read_client.query_order(symbol, client_order_id)

    def open_orders(self, symbol: str | None = None) -> tuple[Any, ...]:
        return self._read_client.open_orders(symbol)

    def account(self) -> Any:
        return self._read_client.account()

    def order_history(self, symbol: str, *, limit: int = 500) -> tuple[Any, ...]:
        return self._read_client.order_history(symbol, limit=limit)

    def trade_history(self, symbol: str, *, limit: int = 500) -> tuple[Any, ...]:
        return self._read_client.trade_history(symbol, limit=limit)

    # ------------------------------------------------------------------ POST /api/v3/order

    def new_order(
        self,
        symbol: str,
        side: str,                     # "BUY" | "SELL"
        order_type: str,               # "MARKET" | "LIMIT"
        *,
        quantity: float | None = None,
        quote_order_qty: float | None = None,
        price: float | None = None,    # requis pour LIMIT
        client_order_id: str,          # OBLIGATOIRE — généré par OrderLifecycleRepository
        time_in_force: str | None = None,
    ) -> TnOrderResult:
        """Envoie un ordre TESTNET. Ne peut jamais atteindre l'API production."""
        self._guard()
        if not symbol or not side or not order_type:
            raise ValueError("symbol, side et order_type sont obligatoires")
        if not client_order_id or not client_order_id.startswith("jfr-"):
            raise BinanceTestnetError(
                "client_order_id doit commencer par 'jfr-' (généré par OrderLifecycleRepository)"
            )
        if quantity is None and quote_order_qty is None:
            raise ValueError("quantity ou quote_order_qty requis")
        if order_type == "LIMIT" and price is None:
            raise ValueError("price requis pour ordre LIMIT")

        params: list[tuple[str, object]] = [
            ("symbol", symbol),
            ("side", side),
            ("type", order_type),
            ("newClientOrderId", client_order_id),
            ("newOrderRespType", "FULL"),
        ]
        if quantity is not None:
            params.append(("quantity", _fmt_qty(quantity)))
        if quote_order_qty is not None:
            params.append(("quoteOrderQty", _fmt_qty(quote_order_qty)))
        if price is not None:
            params.append(("price", _fmt_price(price)))
        if time_in_force is not None:
            params.append(("timeInForce", time_in_force))
        elif order_type == "LIMIT":
            params.append(("timeInForce", "GTC"))

        row = self._post_signed("/api/v3/order", params)
        return _parse_order_result(row)

    # ------------------------------------------------------------------ DELETE /api/v3/order

    def cancel_order(
        self,
        symbol: str,
        client_order_id: str,
    ) -> TnCancelResult:
        """Annule un ordre testnet par clientOrderId."""
        self._guard()
        if not symbol or not client_order_id:
            raise ValueError("symbol et client_order_id requis")
        row = self._delete_signed(
            "/api/v3/order",
            [("symbol", symbol), ("origClientOrderId", client_order_id)],
        )
        return _parse_cancel_result(row)

    # ------------------------------------------------------------------ implémentation réseau

    def _post_signed(self, path: str, params: list[tuple[str, object]]) -> Any:
        values = list(params)
        values.extend([
            ("recvWindow", self.recv_window_ms),
            ("timestamp", self.clock_ms() + self._clock_offset_ms),
        ])
        payload = urllib.parse.urlencode(values)
        values.append(("signature", self.signer(payload.encode("ascii"))))
        body = urllib.parse.urlencode(values).encode("ascii")
        url = f"{_TESTNET_URL}{path}"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Alladin-Jafar/0.1",
            "X-MBX-APIKEY": self.api_key,
        }
        for attempt in range(self.max_attempts):
            try:
                response = self.transport.request_post(url, headers, body, self.timeout)
            except BinanceTransportError:
                if attempt + 1 >= self.max_attempts:
                    raise
                self.sleep(min(0.25 * (2**attempt), 2.0))
                continue
            if (response.status == 429 or 500 <= response.status < 600) and attempt + 1 < self.max_attempts:
                self.sleep(min(0.25 * (2**attempt), 5.0))
                continue
            return self._decode(response)
        raise AssertionError("unreachable")

    def _delete_signed(self, path: str, params: list[tuple[str, object]]) -> Any:
        values = list(params)
        values.extend([
            ("recvWindow", self.recv_window_ms),
            ("timestamp", self.clock_ms() + self._clock_offset_ms),
        ])
        payload = urllib.parse.urlencode(values)
        values.append(("signature", self.signer(payload.encode("ascii"))))
        query = urllib.parse.urlencode(values)
        url = f"{_TESTNET_URL}{path}?{query}"
        headers = {
            "Accept": "application/json",
            "User-Agent": "Alladin-Jafar/0.1",
            "X-MBX-APIKEY": self.api_key,
        }
        for attempt in range(self.max_attempts):
            try:
                response = self.transport.request_delete(url, headers, self.timeout)
            except BinanceTransportError:
                if attempt + 1 >= self.max_attempts:
                    raise
                self.sleep(min(0.25 * (2**attempt), 2.0))
                continue
            if (response.status == 429 or 500 <= response.status < 600) and attempt + 1 < self.max_attempts:
                self.sleep(min(0.25 * (2**attempt), 5.0))
                continue
            return self._decode(response)
        raise AssertionError("unreachable")

    @staticmethod
    def _decode(response: HttpResponse) -> Any:
        import json
        try:
            payload = json.loads(response.body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise BinanceResponseError("invalid testnet JSON response", status=response.status) from exc
        if not 200 <= response.status < 300:
            code = payload.get("code") if isinstance(payload, dict) else None
            code = code if isinstance(code, int) else None
            message = payload.get("msg") if isinstance(payload, dict) else None
            safe = message if isinstance(message, str) else "Testnet request rejected"
            raise BinanceResponseError(safe, status=response.status, code=code)
        return payload


# ---------------------------------------------------------------------------
# Construction depuis settings
# ---------------------------------------------------------------------------


def build_testnet_client(
    api_key: str | None,
    private_key_path: Path | None,
    *,
    transport: TnHttpTransport | None = None,
) -> BinanceTestnetOrderClient:
    """Construit le client testnet ou lève BinanceTestnetCredentialsMissing.

    Les tests utilisent des mocks/fixtures et n'appellent pas cette fonction.
    """
    if not api_key or not private_key_path:
        raise BinanceTestnetCredentialsMissing(
            "Credentials testnet absents. Pour activer le mode TESTNET, configurer :\n"
            "  BINANCE_TESTNET_API_KEY=<votre clé testnet>\n"
            "  BINANCE_TESTNET_PRIVATE_KEY_PATH=<chemin vers clé Ed25519 testnet>\n"
            "Ces variables sont DISTINCTES de BINANCE_API_KEY (production read-only).\n"
            "Obtenir des credentials testnet : https://testnet.binance.vision/"
        )
    if not private_key_path.exists():
        raise BinanceTestnetCredentialsMissing(
            f"Clé privée testnet introuvable : {private_key_path}\n"
            "Vérifier BINANCE_TESTNET_PRIVATE_KEY_PATH."
        )
    signer = Ed25519PemSigner(private_key_path)
    return BinanceTestnetOrderClient(api_key=api_key, signer=signer, transport=transport)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt_qty(qty: float) -> str:
    return f"{qty:.8f}".rstrip("0").rstrip(".")


def _fmt_price(price: float) -> str:
    return f"{price:.8f}".rstrip("0").rstrip(".")


def _parse_order_result(row: Any) -> TnOrderResult:
    if not isinstance(row, dict):
        raise BinanceResponseError("invalid testnet order response", status=200)
    try:
        fills_raw = row.get("fills", [])
        fills = tuple(
            TnFill(
                price=_finite_float(f["price"], "fill price"),
                qty=_finite_float(f["qty"], "fill qty"),
                commission=_finite_float(f["commission"], "fill commission"),
                commission_asset=str(f["commissionAsset"]),
            )
            for f in fills_raw
            if isinstance(f, dict)
        )
        return TnOrderResult(
            symbol=str(row["symbol"]),
            order_id=int(row["orderId"]),
            client_order_id=str(row["clientOrderId"]),
            transact_time=_timestamp(row["transactTime"]),
            price=_finite_float(row["price"], "order price"),
            original_qty=_finite_float(row["origQty"], "origQty"),
            executed_qty=_finite_float(row["executedQty"], "executedQty"),
            status=str(row["status"]),
            side=str(row["side"]),
            order_type=str(row["type"]),
            fills=fills,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise BinanceResponseError("invalid testnet order result", status=200) from exc


def _parse_cancel_result(row: Any) -> TnCancelResult:
    if not isinstance(row, dict):
        raise BinanceResponseError("invalid testnet cancel response", status=200)
    try:
        return TnCancelResult(
            symbol=str(row["symbol"]),
            order_id=int(row["orderId"]),
            client_order_id=str(row["clientOrderId"]),
            status=str(row["status"]),
            orig_client_order_id=str(row.get("origClientOrderId", "")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise BinanceResponseError("invalid testnet cancel result", status=200) from exc
