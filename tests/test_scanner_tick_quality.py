"""Deterministic tick-quality regression tests."""
import math

import pytest

from alladin.market.scanner import tick_quality_error


@pytest.mark.parametrize("bid,ask,age", [
    (1.0, 1.0, 0.0),
    (1.1, 1.0, 0.0),
    (0.0, 1.0, 0.0),
    (math.nan, 1.0, 0.0),
    (1.0, math.inf, 0.0),
    (1.0, 1.1, math.nan),
    (1.0, 1.1, math.inf),
])
def test_bad_quote_rejected(bid: float, ask: float, age: float) -> None:
    assert tick_quality_error(bid, ask, age, 180.0) is not None


def test_future_tick_rejected() -> None:
    assert "futur" in (tick_quality_error(1.0, 1.1, -10800.0, 180.0) or "")
    assert "futur" in (tick_quality_error(1.0, 1.1, -5.1, 180.0) or "")


def test_small_clock_skew_allowed() -> None:
    assert tick_quality_error(1.0, 1.1, -1.0, 180.0) is None


def test_stale_tick_rejected() -> None:
    assert "périmé" in (tick_quality_error(1.0, 1.1, 181.0, 180.0) or "")


def test_fresh_tick_accepted() -> None:
    assert tick_quality_error(1.0, 1.1, 0.94, 180.0) is None
