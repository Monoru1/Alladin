from datetime import UTC, datetime

import pytest

from alladin.brokers.binance import BinanceAccount, BinanceBalance
from alladin.risk.portfolio import PortfolioError, PortfolioLimits, SpotPortfolioEngine

T0 = datetime(2026, 10, 4, 12, tzinfo=UTC)


def account(*balances: BinanceBalance) -> BinanceAccount:
    return BinanceAccount(
        observed_at=T0,
        can_trade=False,
        can_withdraw=False,
        can_deposit=True,
        permissions=("SPOT",),
        balances=balances,
    )


def test_spot_portfolio_values_cash_holdings_fees_and_drawdown():
    source = account(
        BinanceBalance(asset="USDT", free=1000, locked=0),
        BinanceBalance(asset="BTC", free=0.01, locked=0.005),
    )
    snapshot = SpotPortfolioEngine().snapshot(
        source, {"BTC": 60_000}, peak_value=2000, realized_pnl=50, unrealized_pnl=-10, fees=2
    )
    assert snapshot.cash_value == 1000
    assert snapshot.invested_value == pytest.approx(900)
    assert snapshot.total_value == pytest.approx(1900)
    assert snapshot.drawdown_pct == pytest.approx(5)
    assert snapshot.exposure_by_asset == {"BTC": pytest.approx(900)}


def test_same_underlying_is_aggregated_in_one_asset_and_correlation_group():
    source = account(
        BinanceBalance(asset="USDT", free=500, locked=0),
        BinanceBalance(asset="BTC", free=0.02, locked=0),
        BinanceBalance(asset="WBTC", free=0.01, locked=0),
    )
    engine = SpotPortfolioEngine(correlation_groups={"BTC": "BTC_BETA", "WBTC": "BTC_BETA"})
    snapshot = engine.snapshot(source, {"BTC": 50_000, "WBTC": 50_000})
    assert snapshot.exposure_by_asset == {"BTC": 1000, "WBTC": 500}
    assert snapshot.exposure_by_group == {"BTC_BETA": 1500}
    result = engine.assess(
        snapshot,
        PortfolioLimits(
            max_invested_pct=80,
            max_asset_concentration_pct=60,
            max_group_concentration_pct=70,
            max_drawdown_pct=10,
        ),
    )
    assert not result.approved
    assert "CORRELATED_GROUP_EXCEEDED" in result.reasons


def test_missing_mark_and_incoherent_peak_fail_closed():
    source = account(BinanceBalance(asset="ETH", free=1, locked=0))
    engine = SpotPortfolioEngine()
    with pytest.raises(PortfolioError, match="mark"):
        engine.snapshot(source, {})
    with pytest.raises(PortfolioError, match="peak"):
        engine.snapshot(source, {"ETH": 3000}, peak_value=2000)


def test_portfolio_limits_bound_downside_without_profit_target():
    source = account(
        BinanceBalance(asset="USDT", free=400, locked=0), BinanceBalance(asset="ETH", free=2, locked=0)
    )
    engine = SpotPortfolioEngine()
    snapshot = engine.snapshot(source, {"ETH": 300}, peak_value=1200)
    limits = PortfolioLimits(
        max_invested_pct=40,
        max_asset_concentration_pct=45,
        max_group_concentration_pct=45,
        max_drawdown_pct=10,
    )
    result = engine.assess(snapshot, limits)
    assert not result.approved
    assert set(result.reasons) == {
        "MAX_INVESTED_EXCEEDED",
        "ASSET_CONCENTRATION_EXCEEDED",
        "CORRELATED_GROUP_EXCEEDED",
        "MAX_DRAWDOWN_EXCEEDED",
    }
    assert result.remaining_investment_budget == 0
