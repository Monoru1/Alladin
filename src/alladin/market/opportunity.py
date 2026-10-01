"""Modèle Opportunity : résultat qualifié d'un cycle de scan.

Chaque opportunité représente un candidat qui a survécu au filtrage
et est prêt pour l'évaluation agent / RiskEngine.

Lifecycle :
    SEEN → FILTERED (rejet scanner) ou
    SEEN → WATCH → QUALIFIED → AGENT_REVIEW → RISK_REVIEW → EXECUTED | REJECTED | PAPER | EXPIRED
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from alladin.core.enums import MarketRegime, Side, Timeframe


class OpportunityStatus(StrEnum):
    SEEN = "SEEN"
    FILTERED = "FILTERED"
    WATCH = "WATCH"
    QUALIFIED = "QUALIFIED"
    AGENT_REVIEW = "AGENT_REVIEW"
    RISK_REVIEW = "RISK_REVIEW"
    REJECTED = "REJECTED"
    PAPER = "PAPER"
    EXECUTED = "EXECUTED"
    EXPIRED = "EXPIRED"


class Opportunity(BaseModel):
    """Une opportunité de marché observée lors d'un cycle de scan."""

    opportunity_id: str
    cycle_id: str
    run_id: str

    # Instrument
    symbol: str
    timeframe: Timeframe

    # Snapshot de marché au moment du scan
    timestamp: datetime
    bid: float
    ask: float
    spread: float
    atr: float | None = None
    spread_atr_ratio: float | None = None

    # Contexte
    regime: MarketRegime = MarketRegime.UNKNOWN
    regime_confidence: float | None = None
    session: str = ""

    # Signal
    direction: Side | None = None
    strategy_candidates: list[str] = Field(default_factory=list)
    setup_score: float = 0.0
    planned_rr: float | None = None

    # Rejection
    rejection_reasons: list[str] = Field(default_factory=list)

    # Lifecycle
    status: OpportunityStatus = OpportunityStatus.SEEN

    # Métadonnées
    extra: dict[str, Any] = Field(default_factory=dict)

    def to_journal(self) -> dict[str, Any]:
        """Sérialisation pour le journal (exclut les champs volumineux)."""
        return {
            "opportunity_id": self.opportunity_id,
            "symbol": self.symbol,
            "timeframe": self.timeframe.value,
            "regime": self.regime.value,
            "regime_confidence": self.regime_confidence,
            "direction": self.direction.value if self.direction else None,
            "setup_score": round(self.setup_score, 4),
            "planned_rr": self.planned_rr,
            "spread_atr_ratio": round(self.spread_atr_ratio, 4) if self.spread_atr_ratio is not None else None,
            "strategy_candidates": self.strategy_candidates,
            "status": self.status.value,
            "rejection_reasons": self.rejection_reasons,
        }
