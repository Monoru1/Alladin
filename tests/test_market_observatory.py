"""Read-only observatory contract tests, no broker needed."""
from datetime import UTC, datetime, timedelta

import pytest

from alladin.challenge.market_observatory import Annotation, Candle, observatory_snapshot

T = datetime(2026, 10, 8, 12, tzinfo=UTC)


def candle(received):
    return Candle("EURUSD", "1m", T, received, 1.1, 1.2, 1.0, 1.15, 20.0)


def test_causal_visibility_and_annotation():
    marker = Annotation("release", "EURUSD", T + timedelta(seconds=4), "MACRO", "CPI")
    payload = observatory_snapshot(
        candles=(candle(T + timedelta(seconds=3)),), annotations=(marker,),
        symbol="EURUSD", timeframe="1m", as_of=T + timedelta(seconds=3),
    )
    assert len(payload["candles"]) == 1
    assert payload["annotations"] == []
    later = observatory_snapshot(
        candles=(candle(T + timedelta(seconds=3)),), annotations=(marker,),
        symbol="EURUSD", timeframe="1m", as_of=T + timedelta(seconds=5),
    )
    assert later["annotations"][0]["id"] == "release"


def test_future_candle_hidden():
    payload = observatory_snapshot(
        candles=(candle(T + timedelta(seconds=3)),), annotations=(),
        symbol="EURUSD", timeframe="1m", as_of=T,
    )
    assert payload["candles"] == []


def test_duplicate_candle_refused():
    with pytest.raises(ValueError):
        observatory_snapshot(
            candles=(candle(T), candle(T)), annotations=(),
            symbol="EURUSD", timeframe="1m", as_of=T,
        )


def test_invalid_ohlc_refused():
    with pytest.raises(ValueError):
        Candle("EURUSD", "1m", T, T, 1.1, 1.0, 0.9, 1.2, 20.0)
