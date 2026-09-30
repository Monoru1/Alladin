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
    cycle_id: str | None = None
    archived_bars: int = 0

    def summary(self) -> dict[str, object]:
        return {
            "cycle_id": self.cycle_id,
            "universe_size": self.universe_size,
            "analysed": self.analysed,
            "rejected_count": len(self.rejected),
            "shortlist": [c.symbol for c in self.candidates],
            "candidates": [
                {
                    "symbol": c.symbol,
                    "category": c.category.value,
                    "regime": c.regime.value,
                    "bias": c.bias.value if c.bias else None,
                    "score": c.score,
                    "spread_points": round(c.spread_points, 2),
                    "spread_atr_ratio": round(c.spread_atr_ratio, 4),
                    "atr": c.metrics.get("atr"),
                    "atr_pct_rank": c.metrics.get("atr_pct_rank"),
                    "session": c.session,
                    "reasons": c.regime_reasons,
                }
                for c in self.candidates
            ],
            "rejected": self.rejected,
            "regime_counts": self.regime_counts,
            "archived_bars": self.archived_bars,
            "notes": self.notes,
        }
