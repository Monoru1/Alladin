"""HTML rendering and source-origin regression tests."""
from datetime import UTC, datetime

import pytest

from alladin.challenge.market_preview import render_market_preview
from alladin.challenge.official_signals import OfficialPublication, OfficialSource

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)


def test_static_market_preview_escapes_untrusted_text():
    html = render_market_preview({
        "symbol": "<script>alert(1)</script>", "timeframe": "1m",
        "candles": [{"time": "now", "open": 1, "high": 2, "low": 0,
                     "close": 1, "volume": 5}],
        "annotations": [{"kind": "MACRO", "label": "<img src=x onerror=alert(1)>"}],
    })
    assert "<script>" not in html
    assert "<img" not in html
    assert "&lt;script&gt;" in html
    assert "No order controls" in html


@pytest.mark.parametrize("host", [
    "central.example.org.", "-central.example.org", "central..example.org",
    "central.example.org:8443", "central.example.org/path",
])
def test_ambiguous_official_hostname_rejected(host):
    with pytest.raises(ValueError):
        OfficialSource("central", host)


@pytest.mark.parametrize("url", [
    "https://central.example.org./news",
    "https://central.example.org:8443/news",
    "https://central.example.org@evil.example/news",
])
def test_ambiguous_publication_url_rejected(url):
    with pytest.raises(ValueError):
        OfficialPublication("central", "p1", url, "notice", NOW, NOW, "FACT")
