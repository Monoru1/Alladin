"""Abstraction Strategy : un outil de la bibliothèque, versionné, avec ses régimes compatibles."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Any, ClassVar

from pydantic import BaseModel

from alladin.core.enums import EntryType, MarketRegime, Side, Timeframe
from alladin.core.models import Bar, TradeIntent
from alladin.market.models import ScanCandidate

SIGNAL_TTL = timedelta(minutes=15)


class StrategyContext(BaseModel):
    run_id: str
    now: datetime
    candidate: ScanCandidate

    @property
    def bars(self) -> list[Bar]:
        return self.candidate.bars.get(Timeframe.H1, [])


class StrategySignal(BaseModel):
    side: Side
    entry: float  # prix de référence (le prix d'exécution réel sera le prix live)
    stop_loss: float
    take_profit: float | None
    confidence: float
    reason: str


def risk_pct_from_confidence(confidence: float, base: float = 1.0, max_pct: float = 6.0) -> float:
    """Demande de risque (% du capital de travail) : jamais un défaut de 8 %, le RiskEngine tranche."""
    return round(min(max_pct, max(base, base + (max_pct - base) * max(0.0, confidence - 0.5) / 0.5)), 2)


class Strategy(ABC):
    id: ClassVar[str]
    version: ClassVar[str]
    compatible_regimes: ClassVar[frozenset[MarketRegime]]
    description: ClassVar[str] = ""

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self.params = params or {}

    @abstractmethod
    def evaluate(self, ctx: StrategyContext) -> StrategySignal | None:
        """Retourne un signal ou None (aucun setup). Pur : aucun accès broker."""

    def is_compatible(self, regime: MarketRegime) -> bool:
        return regime in self.compatible_regimes

    def to_intent(self, signal: StrategySignal, ctx: StrategyContext, agent: str = "strategy") -> TradeIntent:
        cand = ctx.candidate
        return TradeIntent(
            run_id=ctx.run_id,
            agent=agent,
            instrument=cand.symbol,
            side=signal.side,
            strategy_id=self.id,
            strategy_version=self.version,
            market_regime=cand.regime,
            entry_type=EntryType.MARKET,
            entry=signal.entry,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            requested_risk_pct_of_working_capital=risk_pct_from_confidence(
                signal.confidence,
                base=float(self.params.get("base_risk_pct", 1.0)),
                max_pct=float(self.params.get("max_risk_pct", 6.0)),
            ),
            confidence=signal.confidence,
            reason=signal.reason,
            expires_at=ctx.now + SIGNAL_TTL,
            sources=[f"{self.id}@{self.version}", "market_scanner"],
        )
