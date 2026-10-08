"""Regression checks for CFD/Forex stop geometry (no broker connection)."""
from __future__ import annotations

import pytest

from alladin.core.models import InstrumentSpec
from alladin.market.test_order_geometry import stop_distance_in_price, stop_prices


def spec(*, forex: bool | None = False, stops: float = 0) -> InstrumentSpec:
    return InstrumentSpec(
        symbol="NAS100", currency_base="USD", currency_profit="USD", currency_margin="USD",
        digits=1, point=0.1, trade_tick_size=0.1, trade_tick_value=1,
        trade_contract_size=1, volume_min=0.1, volume_max=10, volume_step=0.1,
        is_forex_like=forex, stops_level=stops,
    )


def test_index_requires_price_distance() -> None:
    with pytest.raises(ValueError, match="sl-price-distance"):
        stop_distance_in_price(spec(), sl_pips=20, price_distance=None)


def test_index_stop_geometry() -> None:
    instrument = spec(stops=10)
    distance = stop_distance_in_price(instrument, sl_pips=20, price_distance=20)
    assert stop_prices(instrument, entry=31101.3, direction=1, distance=distance, rr=2) == (
        31081.3, 31141.3
    )


def test_min_stop_rejected() -> None:
    with pytest.raises(ValueError, match="stops_level"):
        stop_distance_in_price(spec(stops=100), sl_pips=20, price_distance=1)


def test_forex_pips_supported() -> None:
    assert stop_distance_in_price(spec(forex=True), sl_pips=20, price_distance=None) == 20.0


@pytest.mark.parametrize("distance", [0, -1, float("nan"), float("inf")])
def test_invalid_distance_rejected(distance: float) -> None:
    with pytest.raises(ValueError):
        stop_distance_in_price(spec(), sl_pips=20, price_distance=distance)


def test_invalid_stop_after_rounding() -> None:
    with pytest.raises(ValueError):
        stop_prices(spec(), entry=10, direction=1, distance=0.01, rr=2)
