"""Tests Binance Testnet adapter — mocks uniquement, aucun réseau."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from alladin.brokers.binance import HttpResponse
from alladin.jafar.testnet import (
    _MAINNET_URL,
    _TESTNET_URL,
    BinanceTestnetCredentialsMissing,
    BinanceTestnetError,
    BinanceTestnetOrderClient,
    TnHttpTransport,
    _parse_cancel_result,
    _parse_order_result,
    build_testnet_client,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_signer(payload: bytes) -> str:
    return "fakesignature"


def _mock_transport() -> MagicMock:
    t = MagicMock(spec=TnHttpTransport)
    return t


def _filled_order_response(
    symbol: str = "BTCUSDT",
    order_id: int = 12345,
    client_order_id: str = "jfr-abc123",
    qty: str = "0.001",
    price: str = "0",
    side: str = "BUY",
    order_type: str = "MARKET",
    executed_qty: str = "0.001",
    fill_price: str = "65000",
) -> bytes:
    return json.dumps({
        "symbol": symbol,
        "orderId": order_id,
        "clientOrderId": client_order_id,
        "transactTime": 1728057600000,
        "price": price,
        "origQty": qty,
        "executedQty": executed_qty,
        "status": "FILLED",
        "side": side,
        "type": order_type,
        "fills": [
            {
                "price": fill_price,
                "qty": qty,
                "commission": "0.065",
                "commissionAsset": "USDT",
            }
        ],
    }).encode()


def _cancel_response(
    symbol: str = "BTCUSDT",
    order_id: int = 12345,
    client_order_id: str = "jfr-abc123",
) -> bytes:
    return json.dumps({
        "symbol": symbol,
        "orderId": order_id,
        "clientOrderId": client_order_id,
        "origClientOrderId": client_order_id,
        "status": "CANCELED",
    }).encode()


# ---------------------------------------------------------------------------
# Sécurité réseau
# ---------------------------------------------------------------------------


class TestTestnetSecurity:
    def test_base_url_is_always_testnet(self) -> None:
        transport = _mock_transport()
        client = BinanceTestnetOrderClient(
            api_key="test-key",
            signer=_fake_signer,
            transport=transport,
        )
        assert client._base_url == _TESTNET_URL
        assert _MAINNET_URL not in client._base_url

    def test_network_tag_is_testnet(self) -> None:
        transport = _mock_transport()
        client = BinanceTestnetOrderClient(
            api_key="test-key",
            signer=_fake_signer,
            transport=transport,
        )
        assert client.NETWORK_TAG == "TESTNET"

    def test_result_has_testnet_tag(self) -> None:
        transport = _mock_transport()
        transport.request_post.return_value = HttpResponse(
            200, {}, _filled_order_response()
        )
        client = BinanceTestnetOrderClient(
            api_key="test-key",
            signer=_fake_signer,
            transport=transport,
        )
        result = client.new_order(
            "BTCUSDT", "BUY", "MARKET",
            quantity=0.001,
            client_order_id="jfr-abc123",
        )
        assert result.network == "TESTNET"

    def test_empty_api_key_raises(self) -> None:
        with pytest.raises(BinanceTestnetError, match="api_key"):
            BinanceTestnetOrderClient(api_key="", signer=_fake_signer)

    def test_guard_prevents_mainnet_url(self) -> None:
        """Vérifier que _guard() lève si base_url est modifié."""
        transport = _mock_transport()
        client = BinanceTestnetOrderClient(
            api_key="test-key",
            signer=_fake_signer,
            transport=transport,
        )
        # Forcer un base_url invalide (contournement interne)
        client._base_url = _MAINNET_URL
        with pytest.raises(BinanceTestnetError, match="SÉCURITÉ"):
            client._guard()


# ---------------------------------------------------------------------------
# new_order
# ---------------------------------------------------------------------------


class TestNewOrder:
    def test_market_buy_filled(self) -> None:
        transport = _mock_transport()
        transport.request_post.return_value = HttpResponse(
            200, {}, _filled_order_response()
        )
        client = BinanceTestnetOrderClient(
            api_key="test-key",
            signer=_fake_signer,
            transport=transport,
        )
        result = client.new_order(
            "BTCUSDT", "BUY", "MARKET",
            quantity=0.001,
            client_order_id="jfr-abc123",
        )
        assert result.symbol == "BTCUSDT"
        assert result.order_id == 12345
        assert result.client_order_id == "jfr-abc123"
        assert result.is_filled
        assert result.avg_fill_price == pytest.approx(65_000.0)
        assert result.total_commission == pytest.approx(0.065)
        assert result.network == "TESTNET"

    def test_requires_jfr_prefix(self) -> None:
        transport = _mock_transport()
        client = BinanceTestnetOrderClient(
            api_key="test-key",
            signer=_fake_signer,
            transport=transport,
        )
        with pytest.raises(BinanceTestnetError, match="jfr-"):
            client.new_order(
                "BTCUSDT", "BUY", "MARKET",
                quantity=0.001,
                client_order_id="bad-prefix-123",
            )

    def test_limit_requires_price(self) -> None:
        transport = _mock_transport()
        client = BinanceTestnetOrderClient(
            api_key="test-key",
            signer=_fake_signer,
            transport=transport,
        )
        with pytest.raises(ValueError, match="price"):
            client.new_order(
                "BTCUSDT", "BUY", "LIMIT",
                quantity=0.001,
                client_order_id="jfr-abc123",
                # price manquant
            )

    def test_post_url_is_testnet(self) -> None:
        """Vérifier que le POST va bien vers testnet.binance.vision."""
        transport = _mock_transport()
        transport.request_post.return_value = HttpResponse(
            200, {}, _filled_order_response()
        )
        client = BinanceTestnetOrderClient(
            api_key="test-key",
            signer=_fake_signer,
            transport=transport,
        )
        client.new_order(
            "BTCUSDT", "BUY", "MARKET",
            quantity=0.001,
            client_order_id="jfr-abc123",
        )
        call_url = transport.request_post.call_args[0][0]
        assert _TESTNET_URL in call_url
        assert _MAINNET_URL not in call_url

    def test_market_sell(self) -> None:
        transport = _mock_transport()
        transport.request_post.return_value = HttpResponse(
            200, {},
            _filled_order_response(side="SELL", order_id=99999),
        )
        client = BinanceTestnetOrderClient(
            api_key="test-key",
            signer=_fake_signer,
            transport=transport,
        )
        result = client.new_order(
            "BTCUSDT", "SELL", "MARKET",
            quantity=0.001,
            client_order_id="jfr-sell123",
        )
        assert result.side == "SELL"
        assert result.order_id == 99999


# ---------------------------------------------------------------------------
# cancel_order
# ---------------------------------------------------------------------------


class TestCancelOrder:
    def test_cancel_success(self) -> None:
        transport = _mock_transport()
        transport.request_delete.return_value = HttpResponse(
            200, {}, _cancel_response()
        )
        client = BinanceTestnetOrderClient(
            api_key="test-key",
            signer=_fake_signer,
            transport=transport,
        )
        result = client.cancel_order("BTCUSDT", "jfr-abc123")
        assert result.status == "CANCELED"
        assert result.network == "TESTNET"

    def test_delete_url_is_testnet(self) -> None:
        transport = _mock_transport()
        transport.request_delete.return_value = HttpResponse(
            200, {}, _cancel_response()
        )
        client = BinanceTestnetOrderClient(
            api_key="test-key",
            signer=_fake_signer,
            transport=transport,
        )
        client.cancel_order("BTCUSDT", "jfr-abc123")
        call_url = transport.request_delete.call_args[0][0]
        assert _TESTNET_URL in call_url
        assert _MAINNET_URL not in call_url


# ---------------------------------------------------------------------------
# build_testnet_client
# ---------------------------------------------------------------------------


class TestBuildTestnetClient:
    def test_missing_api_key_raises(self) -> None:
        with pytest.raises(BinanceTestnetCredentialsMissing):
            build_testnet_client(None, Path("/some/key.pem"))

    def test_missing_key_path_raises(self) -> None:
        with pytest.raises(BinanceTestnetCredentialsMissing):
            build_testnet_client("api-key", None)

    def test_missing_key_file_raises(self) -> None:
        with pytest.raises(BinanceTestnetCredentialsMissing, match="introuvable"):
            build_testnet_client("api-key", Path("/nonexistent/key.pem"))

    def test_error_message_mentions_env_vars(self) -> None:
        try:
            build_testnet_client(None, None)
        except BinanceTestnetCredentialsMissing as exc:
            assert "BINANCE_TESTNET_API_KEY" in str(exc)
            assert "BINANCE_TESTNET_PRIVATE_KEY_PATH" in str(exc)


# ---------------------------------------------------------------------------
# parse helpers
# ---------------------------------------------------------------------------


class TestParseHelpers:
    def test_parse_order_result(self) -> None:
        row = json.loads(_filled_order_response())
        result = _parse_order_result(row)
        assert result.symbol == "BTCUSDT"
        assert result.is_filled
        assert len(result.fills) == 1
        assert result.fills[0].qty == pytest.approx(0.001)

    def test_parse_cancel_result(self) -> None:
        row = json.loads(_cancel_response())
        result = _parse_cancel_result(row)
        assert result.status == "CANCELED"
        assert result.orig_client_order_id == "jfr-abc123"

    def test_parse_invalid_row_raises(self) -> None:
        from alladin.brokers.binance import BinanceResponseError

        with pytest.raises(BinanceResponseError):
            _parse_order_result("not a dict")
