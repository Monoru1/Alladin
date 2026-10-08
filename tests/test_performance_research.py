"""Research-only performance tests with synthetic net P&L."""
from datetime import UTC, datetime, timedelta

import pytest

from alladin.challenge.performance_research import (
    ClosedTrade,
    evaluate_closed_trades,
    evaluate_holdout,
)

T = datetime(2026, 10, 8, tzinfo=UTC)


def trade(i, pnl):
    return ClosedTrade(f"t{i}", T + timedelta(minutes=i), pnl)


def test_net_expectancy_profit_factor_and_drawdown():
    report = evaluate_closed_trades(
        (trade(1, 100), trade(2, -200), trade(3, 150)), starting_equity_minor=1000
    )
    assert report.total_net_minor == 50
    assert report.trades == 3
    assert report.win_rate == pytest.approx(2 / 3)
    assert report.profit_factor == pytest.approx(1.25)
    assert report.max_drawdown_minor == 200
    assert report.expectancy_minor == pytest.approx(50 / 3)


def test_insufficient_holdout_never_qualifies():
    report = evaluate_holdout(
        training=(trade(1, 100),), holdout=(trade(2, 100),),
        starting_equity_minor=1000,
    )
    assert not report.sufficient_evidence
    assert "INSUFFICIENT_HOLDOUT_SAMPLE" in report.warnings


def test_negative_holdout_never_qualifies():
    report = evaluate_holdout(
        training=(trade(1, 100),),
        holdout=tuple(trade(i, -1) for i in range(2, 32)),
        starting_equity_minor=1000,
    )
    assert not report.sufficient_evidence
    assert "NONPOSITIVE_HOLDOUT_NET" in report.warnings


def test_overlap_and_duplicate_rejected():
    with pytest.raises(ValueError):
        evaluate_holdout(
            training=(trade(1, 100),), holdout=(trade(1, 100),),
            starting_equity_minor=1000,
        )
    with pytest.raises(ValueError):
        evaluate_closed_trades((trade(1, 100), trade(1, 200)), starting_equity_minor=1000)


def test_empty_is_unknown_not_zero_win_rate():
    report = evaluate_closed_trades((), starting_equity_minor=1000)
    assert report.win_rate is None
    assert report.expectancy_minor is None
    assert report.profit_factor is None
