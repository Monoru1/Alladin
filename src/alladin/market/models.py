"""Modèles du scanner de marché."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from alladin.core.enums import AssetCategory, MarketRegime, Side, Timeframe
from alladin.core.models import Bar, InstrumentSpec, Tick


class ScanCandidate(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    symbol: str
    category: AssetCategory
    regime: MarketRegime
    regime_confidence: float
    regime_reasons: list[str] = []
    score: float  # 0..1 : attrait relatif, PAS une probabilité de gain
    bias: Side | None = None
    session: str = ""
    spread_points: float = 0.0
    spread_atr_ratio: float = 0.0
    metrics: dict[str, float] = {}
    tf_trend: dict[str, int] = {}  # +1 / -1 / 0 par timeframe
    # Données brutes transmises aux stratégies (exclues du journal : trop volumineuses)
    spec: InstrumentSpec | None = Field(default=None, exclude=True)
    tick: Tick | None = Field(default=None, exclude=True)
    bars: dict[Timeframe, list[Bar]] = Field(default_factory=dict, exclude=True)


class ScanReport(BaseModel):
    scanned_at: datetime
    universe_size: int
    analysed: int
    candidates: list[ScanCandidate]  # shortlist triée par score décroissant
    rejected: dict[str, list[str]] = {}  # symbole -> raisons
    regime_counts: dict[str, int] = {}
    notes: list[str] = []

    def summary(self) -> dict[str, object]:
        return {
            "universe_size": self.universe_size,
            "analysed": self.analysed,
            "shortlist": [c.symbol for c in self.candidates],
            "rejected": self.rejected,
            "regime_counts": self.regime_counts,
            "notes": self.notes,
        }
