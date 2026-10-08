"""TradingView observation must never imply broker execution."""
import pytest

from alladin.market.tradingview_observe import chart_url, parse_observed_alert


def test_chart_mapping() -> None:
    assert "PEPPERSTONE:NAS100" in chart_url("NAS100")


def test_unverified_alert_is_inert() -> None:
    alert = parse_observed_alert('{"symbol":"NAS100","side":"BUY","timestamp":"2026-10-08T16:00:00Z"}')
    assert alert.executable is False
    assert alert.source == "TRADINGVIEW_UNVERIFIED"


@pytest.mark.parametrize("raw", [
    '{"symbol":"NAS100","side":"BUY","timestamp":"now","execute":true}',
    '{"symbol":"UNKNOWN","side":"BUY","timestamp":"now"}',
    '{"symbol":"NAS100","side":"HOLD","timestamp":"now"}',
    '[]',
])
def test_untrusted_alert_rejected(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_observed_alert(raw)
