"""StrategyRouter : « quel est le marché, et quel outil de la bibliothèque convient ? »"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from alladin.core.enums import MarketRegime
from alladin.market.models import ScanCandidate
from alladin.strategies.base import Strategy
from alladin.strategies.registry import StrategyRegistry


class PerformanceProvider(Protocol):
    def expectancy_r(self, strategy_id: str, strategy_version: str, regime: MarketRegime) -> float | None:
        """Espérance en R mesurée pour ce couple stratégie/régime (None si pas assez de données)."""


class RouteDecision(BaseModel):
    symbol: str
    regime: MarketRegime
    selected: list[str]  # ids de stratégies à évaluer, par ordre de priorité
    skipped: dict[str, str] = {}  # id -> raison


class StrategyRouter:
    def __init__(self, registry: StrategyRegistry, performance: PerformanceProvider | None = None) -> None:
        self.registry = registry
        self.performance = performance

    def route(self, candidate: ScanCandidate) -> tuple[RouteDecision, list[Strategy]]:
        selected: list[tuple[float, Strategy]] = []
        skipped: dict[str, str] = {}
        for strat in self.registry.enabled():
            if not strat.is_compatible(candidate.regime):
                skipped[strat.id] = f"incompatible avec le régime {candidate.regime.value}"
                continue
            perf = (
                self.performance.expectancy_r(strat.id, strat.version, candidate.regime)
                if self.performance
                else None
            )
            selected.append((perf if perf is not None else 0.0, strat))
        selected.sort(key=lambda t: t[0], reverse=True)
        strategies = [s for _, s in selected]
        decision = RouteDecision(
            symbol=candidate.symbol,
            regime=candidate.regime,
            selected=[s.id for s in strategies],
            skipped=skipped,
        )
        return decision, strategies
