"""Public metadata parser tests use recorded-shaped fixtures, never the network."""
import json
from io import BytesIO

import pytest

from alladin.brokers.crypto import BinancePublicProvider


def payload():
    return {"symbols": [{"symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT",
                         "status": "TRADING", "isSpotTradingAllowed": True,
                         "filters": [{"filterType": "PRICE_FILTER", "tickSize": "0.10"},
                                     {"filterType": "LOT_SIZE", "minQty": "0.0001",
                                      "maxQty": "900", "stepSize": "0.0001"},
                                     {"filterType": "MIN_NOTIONAL", "minNotional": "5"}]}]}


def response(monkeypatch, data):
    import urllib.request
    urls = []
    def open_fixture(url, timeout):
        urls.append(url)
        return BytesIO(json.dumps(data).encode())
    monkeypatch.setattr(urllib.request, "urlopen", open_fixture)
    return urls


@pytest.mark.parametrize("filter_type", ["MIN_NOTIONAL", "NOTIONAL"])
def test_spot_metadata_uses_exchange_rules_not_hardcoded_defaults(monkeypatch, filter_type):
    data = payload()
    data["symbols"][0]["filters"][2]["filterType"] = filter_type
    urls = response(monkeypatch, data)
    spec = BinancePublicProvider(testnet=True).instrument("BTCUSDT")
    assert spec and spec.tick_size == 0.1 and spec.lot_size == 0.0001
    assert spec.min_qty == 0.0001 and spec.max_qty == 900 and spec.min_notional == 5
    assert "/api/v3/exchangeInfo?symbol=BTCUSDT" in urls[0]


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
    response(monkeypatch, data)
    assert BinancePublicProvider().instrument("BTCUSDT") is None
