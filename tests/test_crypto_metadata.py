"""Public metadata parser tests use recorded-shaped fixtures, never the network."""

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from alladin.brokers.binance import (
    BinanceClockError,
    BinanceResponseError,
    BinanceRestClient,
    Ed25519PemSigner,
    HttpResponse,
)
from alladin.brokers.crypto import BinancePublicProvider
from alladin.brokers.crypto_observe import CryptoObserveBroker


def payload():
    return {
        "symbols": [
            {
                "symbol": "BTCUSDT",
                "baseAsset": "BTC",
                "quoteAsset": "USDT",
                "status": "TRADING",
                "isSpotTradingAllowed": True,
                "filters": [
                    {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
                    {"filterType": "LOT_SIZE", "minQty": "0.0001", "maxQty": "900", "stepSize": "0.0001"},
                    {"filterType": "MIN_NOTIONAL", "minNotional": "5"},
                ],
            }
        ]
    }


def response(monkeypatch, data):
    del monkeypatch
    transport = FixtureTransport([HttpResponse(200, {}, json.dumps(data).encode())])
    return transport, BinanceRestClient(testnet=True, transport=transport, max_attempts=1)


class FixtureTransport:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def request(self, method, url, headers, timeout):
        self.calls.append((method, url, dict(headers), timeout))
        return self.replies.pop(0)


@pytest.mark.parametrize("filter_type", ["MIN_NOTIONAL", "NOTIONAL"])
def test_spot_metadata_uses_exchange_rules_not_hardcoded_defaults(monkeypatch, filter_type):
    data = payload()
    data["symbols"][0]["filters"][2]["filterType"] = filter_type
    transport, client = response(monkeypatch, data)
    spec = BinancePublicProvider(testnet=True, client=client).instrument("BTCUSDT")
    assert spec and spec.tick_size == 0.1 and spec.lot_size == 0.0001
    assert spec.min_qty == 0.0001 and spec.max_qty == 900 and spec.min_notional == 5
    assert "/api/v3/exchangeInfo?symbol=BTCUSDT" in transport.calls[0][1]


@pytest.mark.parametrize("fault", ["halted", "not_spot", "missing_lot", "nan", "unknown_symbol", "empty"])
def test_metadata_unavailable_is_explicitly_unavailable(monkeypatch, fault):
    data = payload()
    row = data["symbols"][0]
    if fault == "halted":
        row["status"] = "BREAK"
    elif fault == "not_spot":
        row["isSpotTradingAllowed"] = False
    elif fault == "missing_lot":
        row["filters"].pop(1)
    elif fault == "nan":
        row["filters"][0]["tickSize"] = "nan"
    elif fault == "unknown_symbol":
        row["symbol"] = "OTHER"
    else:
        data["symbols"] = []
    _, client = response(monkeypatch, data)
    assert BinancePublicProvider(client=client).instrument("BTCUSDT") is None


def test_dynamic_spot_universe_uses_exchange_catalog_and_reference_currency():
    data = payload()
    eth = json.loads(json.dumps(data["symbols"][0]))
    eth.update(symbol="ETHUSDT", baseAsset="ETH")
    usdc = json.loads(json.dumps(data["symbols"][0]))
    usdc.update(symbol="BTCUSDC", quoteAsset="USDC")
    halted = json.loads(json.dumps(data["symbols"][0]))
    halted.update(symbol="BADUSDT", baseAsset="BAD", status="BREAK")
    data["symbols"] = [data["symbols"][0], eth, usdc, halted]
    transport = FixtureTransport([HttpResponse(200, {}, json.dumps(data).encode())])
    provider = BinancePublicProvider(client=BinanceRestClient(transport=transport, max_attempts=1))
    broker = CryptoObserveBroker(provider)
    assert [item.symbol for item in broker.list_symbols()] == ["BTCUSDT", "ETHUSDT", "BTCUSDC"]
    assert len(transport.calls) == 1  # catalogue cache au lieu d'un exchangeInfo par symbole


def test_public_runtime_filters_dynamic_universe_by_liquidity_and_spread():
    data = payload()
    eth = json.loads(json.dumps(data["symbols"][0]))
    eth.update(symbol="ETHUSDT", baseAsset="ETH")
    illiquid = json.loads(json.dumps(data["symbols"][0]))
    illiquid.update(symbol="LOWUSDT", baseAsset="LOW")
    data["symbols"] = [data["symbols"][0], eth, illiquid]
    stats = [
        {"symbol": "BTCUSDT", "quoteVolume": "9000000"},
        {"symbol": "ETHUSDT", "quoteVolume": "8000000"},
        {"symbol": "LOWUSDT", "quoteVolume": "10"},
    ]
    books = [
        {"symbol": "BTCUSDT", "bidPrice": "99.9", "askPrice": "100.1"},
        {"symbol": "ETHUSDT", "bidPrice": "199.9", "askPrice": "200.1"},
        {"symbol": "LOWUSDT", "bidPrice": "1", "askPrice": "2"},
    ]
    transport = FixtureTransport(
        [HttpResponse(200, {}, json.dumps(item).encode()) for item in (data, stats, books)]
    )
    provider = BinancePublicProvider(client=BinanceRestClient(transport=transport, max_attempts=1))
    broker = CryptoObserveBroker(provider, max_symbols=1)
    assert [item.symbol for item in broker.list_symbols()] == ["BTCUSDT"]
    assert [urlparse(call[1]).path for call in transport.calls] == [
        "/api/v3/exchangeInfo",
        "/api/v3/ticker/24hr",
        "/api/v3/ticker/bookTicker",
    ]


def test_public_universe_summary_keeps_three_classifications():
    data = payload()
    data["serverTime"] = 1000
    halted = json.loads(json.dumps(data["symbols"][0]))
    halted.update(symbol="HALTUSDT", baseAsset="HALT", status="BREAK")
    wrong_quote = json.loads(json.dumps(data["symbols"][0]))
    wrong_quote.update(symbol="BTCBNB", quoteAsset="BNB")
    data["symbols"].extend([halted, wrong_quote])
    transport = FixtureTransport([HttpResponse(200, {}, json.dumps(data).encode())])
    provider = BinancePublicProvider(client=BinanceRestClient(transport=transport, max_attempts=1))
    summary = CryptoObserveBroker(provider).universe_summary()
    assert summary["tradable"] == 1
    assert summary["observe_only"] == 1
    assert summary["ineligible"] == 1


def test_rate_limit_and_transient_server_errors_retry_with_bounded_backoff():
    transport = FixtureTransport(
        [
            HttpResponse(429, {"Retry-After": "0.1"}, b'{"code":-1003,"msg":"rate limited"}'),
            HttpResponse(503, {}, b'{"code":-1000,"msg":"busy"}'),
            HttpResponse(200, {}, b'{"serverTime":1000}'),
        ]
    )
    sleeps = []
    client = BinanceRestClient(transport=transport, max_attempts=3, sleep=sleeps.append)
    assert client.public("/api/v3/time") == {"serverTime": 1000}
    assert sleeps == [0.25, 0.5]


def test_malformed_response_and_terminal_rate_limit_are_explicit():
    malformed = FixtureTransport([HttpResponse(200, {}, b"not-json")])
    with pytest.raises(BinanceResponseError, match="JSON"):
        BinanceRestClient(transport=malformed, max_attempts=1).public("/api/v3/time")
    limited = FixtureTransport([HttpResponse(429, {}, b'{"code":-1003,"msg":"rate limited"}')])
    with pytest.raises(BinanceResponseError) as caught:
        BinanceRestClient(transport=limited, max_attempts=1).public("/api/v3/time")
    assert caught.value.status == 429 and caught.value.code == -1003


def test_signed_request_resynchronizes_clock_once_and_never_exposes_key():
    account = {
        "canTrade": True,
        "canWithdraw": False,
        "canDeposit": True,
        "permissions": ["SPOT"],
        "makerCommission": 10,
        "takerCommission": 20,
        "balances": [{"asset": "USDT", "free": "12.5", "locked": "1.5"}],
    }
    transport = FixtureTransport(
        [
            HttpResponse(400, {}, b'{"code":-1021,"msg":"timestamp outside recvWindow"}'),
            HttpResponse(200, {}, b'{"serverTime":2000}'),
            HttpResponse(200, {}, json.dumps(account).encode()),
        ]
    )
    signed_payloads = []
    client = BinanceRestClient(
        api_key="SECRET-API-KEY",
        signer=lambda value: signed_payloads.append(value) or "sig",
        transport=transport,
        max_attempts=1,
        clock_ms=lambda: 1000,
    )
    result = client.account()
    assert result.balances[0].total == 14 and result.permissions == ("SPOT",)
    assert len(signed_payloads) == 2
    assert parse_qs(urlparse(transport.calls[-1][1]).query)["timestamp"] == ["2000"]
    assert transport.calls[-1][2]["X-MBX-APIKEY"] == "SECRET-API-KEY"
    assert "SECRET-API-KEY" not in str(result)


def test_clock_error_remains_explicit_after_single_resync():
    transport = FixtureTransport(
        [
            HttpResponse(400, {}, b'{"code":-1021,"msg":"clock"}'),
            HttpResponse(200, {}, b'{"serverTime":2000}'),
            HttpResponse(400, {}, b'{"code":-1021,"msg":"clock"}'),
        ]
    )
    client = BinanceRestClient(
        api_key="key", signer=lambda _: "sig", transport=transport, max_attempts=1, clock_ms=lambda: 1000
    )
    with pytest.raises(BinanceClockError):
        client.account()
    assert len(transport.calls) == 3


def test_api_key_restrictions_distinguish_key_permissions_from_account_flags():
    row = {
        "ipRestrict": True,
        "createTime": 1000,
        "enableReading": True,
        "enableWithdrawals": False,
        "enableInternalTransfer": False,
        "enableMargin": False,
        "enableFutures": False,
        "permitsUniversalTransfer": False,
        "enableSpotAndMarginTrading": False,
    }
    transport = FixtureTransport([HttpResponse(200, {}, json.dumps(row).encode())])
    client = BinanceRestClient(
        api_key="key", signer=lambda _: "sig", transport=transport, max_attempts=1, clock_ms=lambda: 1000
    )
    restrictions = client.api_restrictions()
    assert restrictions.safe_for_read_only
    assert restrictions.ip_restricted and not restrictions.spot_margin_trading_enabled
    assert urlparse(transport.calls[0][1]).path == "/sapi/v1/account/apiRestrictions"


@pytest.mark.parametrize("field", ["enableReading", "enableWithdrawals", "enableSpotAndMarginTrading"])
def test_api_key_restrictions_reject_non_boolean_permissions(field):
    row = {
        "ipRestrict": True,
        "createTime": 1000,
        "enableReading": True,
        "enableWithdrawals": False,
        "enableInternalTransfer": False,
        "enableMargin": False,
        "enableFutures": False,
        "permitsUniversalTransfer": False,
        "enableSpotAndMarginTrading": False,
    }
    row[field] = "false"
    transport = FixtureTransport([HttpResponse(200, {}, json.dumps(row).encode())])
    client = BinanceRestClient(
        api_key="key", signer=lambda _: "sig", transport=transport, max_attempts=1, clock_ms=lambda: 1000
    )
    with pytest.raises(BinanceResponseError, match="invalid"):
        client.api_restrictions()


def test_readonly_order_and_trade_history_convert_to_canonical_models():
    order = {
        "symbol": "BTCUSDT",
        "orderId": 1,
        "clientOrderId": "jafar-1",
        "price": "65000",
        "origQty": "0.01",
        "executedQty": "0.005",
        "cummulativeQuoteQty": "325",
        "status": "PARTIALLY_FILLED",
        "type": "LIMIT",
        "side": "BUY",
        "time": 1000,
        "updateTime": 2000,
    }
    trade = {
        "symbol": "BTCUSDT",
        "id": 2,
        "orderId": 1,
        "price": "65000",
        "qty": "0.005",
        "quoteQty": "325",
        "commission": "0.000005",
        "commissionAsset": "BTC",
        "time": 2000,
        "isBuyer": True,
        "isMaker": False,
    }
    transport = FixtureTransport(
        [
            HttpResponse(200, {}, json.dumps([order]).encode()),
            HttpResponse(200, {}, json.dumps([order]).encode()),
            HttpResponse(200, {}, json.dumps([trade]).encode()),
        ]
    )
    client = BinanceRestClient(
        api_key="key", signer=lambda _: "sig", transport=transport, max_attempts=1, clock_ms=lambda: 1000
    )
    assert client.open_orders()[0].status == "PARTIALLY_FILLED"
    assert client.order_history("BTCUSDT")[0].client_order_id == "jafar-1"
    assert client.trade_history("BTCUSDT")[0].quote_quantity == 325
    assert [urlparse(call[1]).path for call in transport.calls] == [
        "/api/v3/openOrders",
        "/api/v3/allOrders",
        "/api/v3/myTrades",
    ]


def test_query_order_uses_persistent_client_id_and_absence_is_not_resubmission():
    order = {
        "symbol": "BTCUSDT",
        "orderId": 1,
        "clientOrderId": "jfr-persistent",
        "price": "65000",
        "origQty": "0.01",
        "executedQty": "0",
        "cummulativeQuoteQty": "0",
        "status": "NEW",
        "type": "LIMIT",
        "side": "BUY",
        "time": 1000,
        "updateTime": 1000,
    }
    transport = FixtureTransport(
        [
            HttpResponse(200, {}, json.dumps(order).encode()),
            HttpResponse(400, {}, b'{"code":-2013,"msg":"Order does not exist"}'),
        ]
    )
    client = BinanceRestClient(
        api_key="key", signer=lambda _: "sig", transport=transport, max_attempts=1
    )
    assert client.query_order("BTCUSDT", "jfr-persistent").order_id == 1  # type: ignore[union-attr]
    assert client.query_order("BTCUSDT", "jfr-absent") is None
    assert all(urlparse(call[1]).path == "/api/v3/order" for call in transport.calls)


def test_ed25519_pem_signer_produces_verifiable_base64(tmp_path: Path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private = Ed25519PrivateKey.generate()
    path = tmp_path / "fixture.pem"
    path.write_bytes(
        private.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )
    payload = b"timestamp=1000&recvWindow=5000"
    import base64

    signature = base64.b64decode(Ed25519PemSigner(path)(payload))
    private.public_key().verify(signature, payload)


def test_public_trades_depth_and_24h_stats_are_canonical():
    trades = [{"id": 1, "price": "100", "qty": "2", "quoteQty": "200", "time": 1000, "isBuyerMaker": True}]
    depth = {"lastUpdateId": 7, "bids": [["99", "3"]], "asks": [["101", "4"]]}
    stats = {
        "lastPrice": "100",
        "volume": "10",
        "quoteVolume": "1000",
        "count": 5,
        "openTime": 1000,
        "closeTime": 2000,
    }
    transport = FixtureTransport(
        [HttpResponse(200, {}, json.dumps(item).encode()) for item in (trades, depth, stats)]
    )
    provider = BinancePublicProvider(client=BinanceRestClient(transport=transport, max_attempts=1))
    assert provider.recent_trades("BTCUSDT")[0].quote_quantity == 200
    assert provider.order_book("BTCUSDT", limit=100).bids[0] == (99, 3)  # type: ignore[union-attr]
    assert provider.market_stats("BTCUSDT").quote_volume == 1000  # type: ignore[union-attr]
    assert [urlparse(call[1]).path for call in transport.calls] == [
        "/api/v3/trades",
        "/api/v3/depth",
        "/api/v3/ticker/24hr",
    ]


@pytest.mark.parametrize("fault", ["crossed", "empty", "nan"])
def test_invalid_order_book_fails_closed(fault):
    row = {"lastUpdateId": 7, "bids": [["99", "3"]], "asks": [["101", "4"]]}
    if fault == "crossed":
        row["bids"][0][0] = "102"
    elif fault == "empty":
        row["asks"] = []
    else:
        row["bids"][0][1] = "nan"
    transport = FixtureTransport([HttpResponse(200, {}, json.dumps(row).encode())])
    provider = BinancePublicProvider(client=BinanceRestClient(transport=transport, max_attempts=1))
    assert provider.order_book("BTCUSDT") is None
