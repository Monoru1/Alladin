"""Read-only market observatory contract: causal candles and annotations.

Designed for Mission Control consumers. No charting CDN, network, broker calls,
order entry, or mutation of runtime state. Feed adapters must be explicit.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from typing import Literal


def _stamp(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("aware timestamp required")
    return value.astimezone(UTC)


@dataclass(frozen=True)
class Candle:
    symbol: str
    timeframe: str
    opens_at: datetime
    available_at: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self) -> None:
        if not self.symbol.strip() or not self.timeframe.strip():
            raise ValueError("explicit symbol and timeframe required")
        if _stamp(self.available_at) < _stamp(self.opens_at):
            raise ValueError("candle availability precedes open")
        values = (self.open, self.high, self.low, self.close, self.volume)
        if not all(isfinite(x) for x in values) or self.volume < 0:
            raise ValueError("invalid candle values")
        if self.high < max(self.open, self.close, self.low) or self.low > min(self.open, self.close, self.high):
            raise ValueError("invalid OHLC bounds")


@dataclass(frozen=True)
class Annotation:
    event_id: str
    symbol: str
    available_at: datetime
    kind: Literal["MACRO", "OFFICIAL", "PAPER_FILL", "POLICY_REJECT", "STOP", "TARGET"]
    label: str

    def __post_init__(self) -> None:
        if not self.event_id.strip() or not self.symbol.strip() or not self.label.strip():
            raise ValueError("annotation identity required")
        _stamp(self.available_at)


def observatory_snapshot(
    *, candles: tuple[Candle, ...], annotations: tuple[Annotation, ...],
    symbol: str, timeframe: str, as_of: datetime,
) -> dict[str, object]:
    """Produce stable JSON-serializable chart payload without future leakage."""
    now = _stamp(as_of)
    selected = [c for c in candles if c.symbol == symbol and c.timeframe == timeframe
                and _stamp(c.available_at) <= now]
    selected.sort(key=lambda c: _stamp(c.opens_at))
    if len({_stamp(c.opens_at) for c in selected}) != len(selected):
        raise ValueError("duplicate candle open")
    events = sorted(
        (a for a in annotations if a.symbol == symbol and _stamp(a.available_at) <= now),
        key=lambda a: (_stamp(a.available_at), a.event_id),
    )
    if len({a.event_id for a in events}) != len(events):
        raise ValueError("duplicate event id")
    return {
        "symbol": symbol, "timeframe": timeframe, "as_of": now.isoformat(),
        "candles": [
            {"time": _stamp(c.opens_at).isoformat(), "open": c.open, "high": c.high,
             "low": c.low, "close": c.close, "volume": c.volume,
             "available_at": _stamp(c.available_at).isoformat()}
            for c in selected
        ],
        "annotations": [
            {"id": a.event_id, "time": _stamp(a.available_at).isoformat(),
             "kind": a.kind, "label": a.label}
            for a in events
        ],
    }
