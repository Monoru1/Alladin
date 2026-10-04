"""Tests — CryptoUniverseBuilder et pipeline d'éligibilité.

Utilise des fixtures JSON (pas d'appel réseau réel).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from alladin.brokers.binance import BinanceExchangeInfo, BinanceSymbolFilter, BinanceSymbolInfo
from alladin.brokers.crypto_universe import (
    CryptoUniverseBuilder,
    assess_symbol,
)

T0 = datetime(2026, 10, 4, 12, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _filters(*types_and_data: tuple[str, dict]) -> tuple[BinanceSymbolFilter, ...]:
    return tuple(BinanceSymbolFilter(filter_type=ft, **data) for ft, data in types_and_data)


def _symbol(
    symbol: str = "BTCUSDT",
    *,
    status: str = "TRADING",
    base: str = "BTC",
    quote: str = "USDT",
    spot: bool = True,
    order_types: tuple[str, ...] = ("LIMIT", "MARKET", "STOP_LOSS_LIMIT"),
    filters: tuple[BinanceSymbolFilter, ...] | None = None,
) -> BinanceSymbolInfo:
    if filters is None:
        filters = _filters(
            ("LOT_SIZE", {"minQty": "0.00001000", "maxQty": "9000.00", "stepSize": "0.00001000"}),
            ("MIN_NOTIONAL", {"minNotional": "10.00000000", "applyToMarket": True, "avgPriceMins": 5}),
        )
    return BinanceSymbolInfo(
        symbol=symbol, status=status, base_asset=base, quote_asset=quote,
        is_spot_trading_allowed=spot, order_types=order_types, filters=filters,
    )


def _exchange_info(*symbols: BinanceSymbolInfo) -> BinanceExchangeInfo:
    return BinanceExchangeInfo(server_time=T0, symbols=symbols)


# ---------------------------------------------------------------------------
# BinanceSymbolInfo helpers
# ---------------------------------------------------------------------------


class TestBinanceSymbolInfo:
    def test_is_trading_true(self) -> None:
        assert _symbol().is_trading is True

    def test_is_trading_false_when_halt(self) -> None:
        assert _symbol(status="HALT").is_trading is False

    def test_get_filter_found(self) -> None:
        sym = _symbol()
        f = sym.get_filter("LOT_SIZE")
        assert f is not None
        assert f.filter_type == "LOT_SIZE"

    def test_get_filter_not_found(self) -> None:
        sym = _symbol()
        assert sym.get_filter("NONEXISTENT") is None


# ---------------------------------------------------------------------------
# assess_symbol
# ---------------------------------------------------------------------------


class TestAssessSymbol:
    def test_fully_eligible_symbol(self) -> None:
        result = assess_symbol(_symbol())
        assert result.trade_eligible is True
        assert result.observe_eligible is True
        assert result.ineligibility_reasons == ()

    def test_wrong_quote_asset_not_trade_eligible(self) -> None:
        result = assess_symbol(_symbol("BTCBNB", quote="BNB"))
        assert result.trade_eligible is False
        assert "QUOTE_ASSET_NOT_ACCEPTED:BNB" in result.ineligibility_reasons

    def test_wrong_quote_asset_not_observe_eligible(self) -> None:
        result = assess_symbol(_symbol("BTCBNB", quote="BNB"))
        assert result.observe_eligible is False

    def test_halt_status_not_trade_eligible_but_observe_eligible(self) -> None:
        result = assess_symbol(_symbol(status="HALT"))
        assert result.trade_eligible is False
        assert result.observe_eligible is True
        assert any("STATUS_NOT_TRADING" in r for r in result.ineligibility_reasons)

    def test_blacklisted_not_eligible(self) -> None:
        result = assess_symbol(_symbol("BADUSDT", base="BAD"), blacklist=frozenset({"BADUSDT"}))
        assert result.trade_eligible is False
        assert result.observe_eligible is False
        assert "BLACKLISTED" in result.ineligibility_reasons

    def test_spot_not_allowed_not_eligible(self) -> None:
        result = assess_symbol(_symbol(spot=False))
        assert result.trade_eligible is False
        assert result.observe_eligible is False
        assert "SPOT_NOT_ALLOWED" in result.ineligibility_reasons

    def test_missing_lot_size_filter(self) -> None:
        sym = _symbol(filters=_filters(
            ("MIN_NOTIONAL", {"minNotional": "10.0"}),
        ))
        result = assess_symbol(sym)
        assert result.trade_eligible is False
        assert "LOT_SIZE" in " ".join(result.ineligibility_reasons)

    def test_missing_min_notional_filter(self) -> None:
        sym = _symbol(filters=_filters(
            ("LOT_SIZE", {"minQty": "0.0001", "stepSize": "0.0001"}),
        ))
        result = assess_symbol(sym)
        assert result.trade_eligible is False
        assert "MIN_NOTIONAL" in " ".join(result.ineligibility_reasons)

    def test_lot_size_extracted(self) -> None:
        result = assess_symbol(_symbol())
        assert result.lot_size_min_qty == pytest.approx(0.00001)
        assert result.lot_size_step == pytest.approx(0.00001)

    def test_min_notional_extracted(self) -> None:
        result = assess_symbol(_symbol())
        assert result.min_notional == pytest.approx(10.0)

    def test_notional_filter_alternative(self) -> None:
        sym = _symbol(filters=_filters(
            ("LOT_SIZE", {"minQty": "0.0001", "stepSize": "0.0001"}),
            ("NOTIONAL", {"minNotional": "5.0"}),
        ))
        result = assess_symbol(sym)
        assert result.min_notional == pytest.approx(5.0)

    def test_require_market_order_fails_if_missing(self) -> None:
        sym = _symbol(order_types=("LIMIT",))
        result = assess_symbol(sym, require_market_order=True)
        assert result.trade_eligible is False
        assert "MARKET_ORDER_NOT_SUPPORTED" in result.ineligibility_reasons

    def test_require_market_order_passes_if_present(self) -> None:
        result = assess_symbol(_symbol(), require_market_order=True)
        assert result.trade_eligible is True

    def test_supports_market_order(self) -> None:
        assert _symbol().is_spot_trading_allowed is True
        result = assess_symbol(_symbol())
        assert result.supports_market_order is True

    def test_supports_limit_order(self) -> None:
        result = assess_symbol(_symbol())
        assert result.supports_limit_order is True

    def test_usdc_quote_accepted_by_default(self) -> None:
        sym = _symbol("BTCUSDC", quote="USDC")
        result = assess_symbol(sym)
        assert result.trade_eligible is True


# ---------------------------------------------------------------------------
# CryptoUniverseBuilder
# ---------------------------------------------------------------------------


class TestCryptoUniverseBuilder:
    def test_empty_exchange_info(self) -> None:
        report = CryptoUniverseBuilder().build(_exchange_info())
        assert report.total_discovered == 0
        assert report.n_trade_eligible == 0

    def test_single_eligible_symbol(self) -> None:
        report = CryptoUniverseBuilder().build(_exchange_info(_symbol()))
        assert report.n_trade_eligible == 1
        assert report.trade_eligible[0].symbol == "BTCUSDT"

    def test_halt_goes_to_observe_only(self) -> None:
        report = CryptoUniverseBuilder().build(_exchange_info(_symbol(status="HALT")))
        assert report.n_trade_eligible == 0
        assert len(report.observe_only) == 1

    def test_blacklisted_goes_to_ineligible(self) -> None:
        report = CryptoUniverseBuilder(blacklist=frozenset({"BTCUSDT"})).build(
            _exchange_info(_symbol())
        )
        assert report.n_trade_eligible == 0
        assert len(report.ineligible) == 1

    def test_wrong_quote_goes_to_ineligible(self) -> None:
        report = CryptoUniverseBuilder().build(_exchange_info(_symbol("BTCBNB", quote="BNB")))
        assert len(report.ineligible) == 1

    def test_multiple_symbols_classified(self) -> None:
        report = CryptoUniverseBuilder().build(_exchange_info(
            _symbol("BTCUSDT"),
            _symbol("ETHUSDT", base="ETH"),
            _symbol("BTCUSDT_HALT", status="HALT"),
        ))
        assert report.n_trade_eligible == 2
        assert len(report.observe_only) == 1

    def test_by_quote_asset_counts(self) -> None:
        report = CryptoUniverseBuilder().build(_exchange_info(
            _symbol("BTCUSDT"),
            _symbol("BTCUSDC", quote="USDC"),
        ))
        assert report.by_quote_asset.get("USDT", 0) == 1
        assert report.by_quote_asset.get("USDC", 0) == 1

    def test_n_observable_includes_trade_and_observe(self) -> None:
        report = CryptoUniverseBuilder().build(_exchange_info(
            _symbol("BTCUSDT"),
            _symbol("ETHUSDT", base="ETH", status="HALT"),
        ))
        assert report.n_observable == 2

    def test_custom_quote_assets(self) -> None:
        builder = CryptoUniverseBuilder(quote_assets=frozenset({"BNB"}))
        report = builder.build(_exchange_info(
            _symbol("BTCBNB", quote="BNB"),
            _symbol("BTCUSDT"),
        ))
        assert report.n_trade_eligible == 1
        assert report.trade_eligible[0].symbol == "BTCBNB"

    def test_total_discovered_counts_all(self) -> None:
        report = CryptoUniverseBuilder().build(_exchange_info(
            _symbol("BTCUSDT"), _symbol("ETHUSDT", base="ETH"),
        ))
        assert report.total_discovered == 2


# ---------------------------------------------------------------------------
# BinanceExchangeInfo helpers
# ---------------------------------------------------------------------------


class TestBinanceExchangeInfo:
    def test_spot_symbols_filters_by_quote(self) -> None:
        info = _exchange_info(
            _symbol("BTCUSDT"),
            _symbol("BTCUSDC", quote="USDC"),
            _symbol("BTCBNB", quote="BNB"),
        )
        usdt_only = info.spot_symbols("USDT")
        assert len(usdt_only) == 1
        assert usdt_only[0].symbol == "BTCUSDT"

    def test_trading_only_excludes_halt(self) -> None:
        info = _exchange_info(
            _symbol("BTCUSDT"),
            _symbol("ETHUSDT", base="ETH", status="HALT"),
        )
        trading = info.trading_only()
        assert len(trading) == 1
        assert trading[0].symbol == "BTCUSDT"
