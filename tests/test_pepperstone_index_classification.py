"""Tests déterministes de la classification des CFD indices Pepperstone."""

from __future__ import annotations

import pytest

from alladin.core.enums import AssetCategory, SymbolTradeMode
from alladin.core.models import InstrumentSpec
from alladin.market.universe import classify_symbol


def _spec(symbol: str, path: str, *, forex_like: bool | None = False) -> InstrumentSpec:
    return InstrumentSpec(
        symbol=symbol,
        path=path,
        currency_base="",
        currency_profit="USD",
        currency_margin="USD",
        digits=1,
        point=0.1,
        trade_tick_size=0.1,
        trade_tick_value=0.1,
        trade_contract_size=1.0,
        volume_min=0.1,
        volume_max=100.0,
        volume_step=0.1,
        trade_mode=SymbolTradeMode.FULL,
        is_forex_like=forex_like,
    )


@pytest.mark.parametrize("symbol", ["NAS100", "US500", "US30"])
def test_verified_cash_indices(symbol: str) -> None:
    assert classify_symbol(_spec(symbol, rf"Retail\Indices\{symbol}")) is AssetCategory.INDEX


@pytest.mark.parametrize("symbol", ["NAS100-F", "NAS100-PERP", "US500-F", "US30-F", "GOLD"])
def test_derivatives_and_shares_not_promoted(symbol: str) -> None:
    assert classify_symbol(_spec(symbol, rf"Retail\Indices\{symbol}")) is AssetCategory.OTHER


def test_name_alone_is_insufficient() -> None:
    assert classify_symbol(_spec("NAS100", r"Retail\Shares\NAS100")) is AssetCategory.OTHER


def test_unknown_calc_mode_is_not_promoted() -> None:
    assert classify_symbol(_spec("NAS100", r"Retail\Indices\NAS100", forex_like=None)) is AssetCategory.OTHER
