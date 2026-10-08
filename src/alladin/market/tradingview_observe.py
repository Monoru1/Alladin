"""TradingView chart links and inert alert envelopes.

This module is intentionally data-only. No webhook listener, account access,
trade intent construction, broker API or order submission is permitted here.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import quote

_ALLOWED = {"NAS100": "PEPPERSTONE:NAS100", "US500": "PEPPERSTONE:US500",
            "US30": "PEPPERSTONE:US30", "XAUUSD": "PEPPERSTONE:XAUUSD",
            "XAGUSD": "PEPPERSTONE:XAGUSD", "EURUSD": "PEPPERSTONE:EURUSD"}


def chart_url(symbol: str) -> str:
    """Return a chart URL; users must verify the venue mapping on TradingView."""
    if symbol not in _ALLOWED:
        raise ValueError("symbole TradingView non validé dans la table locale")
    return "https://www.tradingview.com/chart/?symbol=" + quote(_ALLOWED[symbol], safe=":")


@dataclass(frozen=True)
class ObservedAlert:
    symbol: str
    side: str
    timestamp: str
    source: str = "TRADINGVIEW_UNVERIFIED"
    executable: bool = False


def parse_observed_alert(raw: str) -> ObservedAlert:
    """Parse an untrusted alert for observation only; fail closed on unknown fields."""
    data = json.loads(raw)
    if not isinstance(data, dict) or set(data) != {"symbol", "side", "timestamp"}:
        raise ValueError("format d'alerte invalide")
    if data["symbol"] not in _ALLOWED or data["side"] not in ("BUY", "SELL"):
        raise ValueError("symbole ou sens inconnu")
    if not isinstance(data["timestamp"], str) or not data["timestamp"]:
        raise ValueError("horodatage absent")
    return ObservedAlert(**data)
