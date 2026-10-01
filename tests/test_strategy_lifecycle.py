"""Tests : Strategy lifecycle enforcement."""

from __future__ import annotations

from alladin.strategies.registry import StrategyRegistry


def test_lifecycle_check_no_violations_when_all_approved() -> None:
    reg = StrategyRegistry()
    from alladin.strategies.trend import Trend01
    reg.register(Trend01)
    from alladin.strategies.registry import StrategyConfig
    reg.activate(StrategyConfig(id="TREND-01", version="1.0.0", enabled=True))

    violations = reg.check_lifecycle({"TREND-01"})
    assert violations == {}


def test_lifecycle_check_violation_when_not_approved() -> None:
    reg = StrategyRegistry()
    from alladin.strategies.trend import Trend01
    reg.register(Trend01)
    from alladin.strategies.registry import StrategyConfig
    reg.activate(StrategyConfig(id="TREND-01", version="1.0.0", enabled=True))

    violations = reg.check_lifecycle(set())
    assert "TREND-01" in violations


def test_lifecycle_strict_removes_unapproved() -> None:
    reg = StrategyRegistry()
    from alladin.strategies.trend import Trend01
    reg.register(Trend01)
    from alladin.strategies.registry import StrategyConfig
    reg.activate(StrategyConfig(id="TREND-01", version="1.0.0", enabled=True))
    assert reg.get("TREND-01") is not None

    reg.check_lifecycle(set(), strict=True)
    assert reg.get("TREND-01") is None
    assert "TREND-01" in reg.unavailable


def test_lifecycle_strict_keeps_approved() -> None:
    reg = StrategyRegistry()
    from alladin.strategies.breakout import Breakout01
    from alladin.strategies.trend import Trend01
    reg.register(Trend01)
    reg.register(Breakout01)
    from alladin.strategies.registry import StrategyConfig
    reg.activate(StrategyConfig(id="TREND-01", version="1.0.0", enabled=True))
    reg.activate(StrategyConfig(id="BREAKOUT-01", version="1.0.0", enabled=True))

    # Only TREND-01 is approved
    reg.check_lifecycle({"TREND-01"}, strict=True)
    assert reg.get("TREND-01") is not None
    assert reg.get("BREAKOUT-01") is None
