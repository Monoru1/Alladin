"""Offline diagnostic rendering contract: deterministic, zero external dependencies.

This intentionally renders only a STATIC chart preview. Real Mission Control
integration requires a read-only adapter to the existing journal and market feed.
"""
from __future__ import annotations

from html import escape
from typing import Any


def render_market_preview(snapshot: dict[str, Any]) -> str:
    """Render a read-only HTML table from an observatory snapshot.

    Strict escaping prevents untrusted symbols and labels becoming HTML.
    No external scripts, JavaScript event handlers or broker capabilities.
    """
    candles = snapshot.get("candles", [])
    annotations = snapshot.get("annotations", [])
    if not isinstance(candles, list) or not isinstance(annotations, list):
        raise ValueError("invalid observatory payload")
    symbol = escape(str(snapshot.get("symbol", "")), quote=True)
    timeframe = escape(str(snapshot.get("timeframe", "")), quote=True)
    rows = []
    for candle in candles:
        if not isinstance(candle, dict):
            raise ValueError("invalid candle")
        values = [escape(str(candle.get(key, "")), quote=True) for key in
                  ("time", "open", "high", "low", "close", "volume")]
        rows.append("<tr>" + "".join(f"<td>{value}</td>" for value in values) + "</tr>")
    notes = []
    for item in annotations:
        if not isinstance(item, dict):
            raise ValueError("invalid annotation")
        notes.append("<li>" + escape(str(item.get("kind", "")), quote=True) + ": " +
                     escape(str(item.get("label", "")), quote=True) + "</li>")
    return (
        "<section aria-label='Market observatory preview'>"
        f"<h2>{symbol} — {timeframe}</h2>"
        "<p>Static offline preview. No order controls.</p>"
        "<table><thead><tr><th>Time</th><th>Open</th><th>High</th>"
        "<th>Low</th><th>Close</th><th>Volume</th></tr></thead><tbody>"
        + "".join(rows) + "</tbody></table><ul>" + "".join(notes) + "</ul></section>"
    )
