"""Reuse existing simulators/watchdog for economic-event stress, not broker qualification."""
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from alladin.challenge.models import WatchdogState
from alladin.challenge.watchdog import ChallengeWatchdog
from alladin.core.enums import RunState, Side
from alladin.core.models import Bar
from alladin.research.backtest import BacktestRunner, VirtualPosition
from tests.test_backtest import DummyStrategy
from tests.test_watchdog import snap


@pytest.mark.parametrize("side,opening,expected", [(Side.BUY, 95., 95.), (Side.SELL, 105., 105.2)])
def test_adverse_news_gap_includes_spread_costs_and_slippage(side, opening, expected):
    now = datetime(2026, 10, 8, 12, tzinfo=UTC)
    runner = BacktestRunner(DummyStrategy(), point=.1, spread_pips=2,
                            commission_per_lot=3, price_value_per_lot=10, slippage=.5, volume=1)
    stop = 99. if side == Side.BUY else 101.
    target = 102. if side == Side.BUY else 98.
    pos = VirtualPosition("stress", "synthetic-index", side, 100., stop, target, now, 0)
    bar = Bar(time=now+timedelta(hours=1), open=opening, high=opening+.1,
              low=opening-.1, close=opening)
    pos.exit_price = runner._check_exit(pos, bar)
    pos.closed_at = bar.time
    assert pos.exit_reason == "SL_GAP" and pos.exit_price == pytest.approx(expected)
    trade = runner._finalize_trade(pos, 1, .2)
    assert trade.fill is not None
    assert trade.fill.net_pnl == pytest.approx((expected-100)*side.sign*10-8)
    assert trade.fill.net_pnl < -10  # gap loss exceeds nominal stop distance


@pytest.mark.parametrize("fold", [0, 1])
def test_watchdog_loss_survives_restart_in_repeated_dst_hour(profile, fold):
    now = datetime(2026, 10, 25, 2, 30, tzinfo=ZoneInfo("Europe/Prague"), fold=fold).astimezone(UTC)
    watchdog = ChallengeWatchdog.create(profile, "synthetic-DST", 100000)
    watchdog.start(snap(100000, now=now), now)
    state = WatchdogState.model_validate_json(watchdog.state.model_dump_json())
    resumed = ChallengeWatchdog(profile, state)
    report = resumed.update(snap(100000, 94000, now+timedelta(seconds=1)), now+timedelta(seconds=1))
    assert report.run_state == RunState.FAILED
    assert report.can_open_new_positions is False
    persisted = WatchdogState.model_validate_json(resumed.state.model_dump_json())
    assert persisted.run_state == RunState.FAILED
