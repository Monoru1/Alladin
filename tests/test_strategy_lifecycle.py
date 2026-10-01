"""Tests : Strategy lifecycle enforcement."""

from __future__ import annotations

from alladin.agents.base import AgentDecision
from alladin.agents.mock import MockAgent
from alladin.core.enums import DecisionKind, RunMode
from alladin.orchestration.bootstrap import Components
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


def test_demo_unapproved_active_strategy_cannot_send_order(svc: Components) -> None:
    from tests.test_orchestration import draft_for, shortlist

    symbol = shortlist(svc)[0]
    agent = MockAgent([AgentDecision(decision=DecisionKind.TRADE,
                                     intent=draft_for(svc, symbol))])
    engine = svc.engine(agent, run_mode=RunMode.DEMO)
    assert engine.router.registry.get("TREND-01") is None
    outcome = engine.run_cycle()
    assert outcome.decision == "NO_TRADE"
    assert svc.broker.sent_orders == []  # type: ignore[attr-defined]


def test_paper_requires_explicit_research_mark(svc: Components) -> None:
    paper = svc.engine(MockAgent(), run_mode=RunMode.PAPER)
    assert paper.router.registry.get("TREND-01") is not None
    assert svc.engine(MockAgent(), run_mode=RunMode.DEMO).router.registry.get("TREND-01") is None
