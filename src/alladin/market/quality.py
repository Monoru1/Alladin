"""Market Quality Engine : evalue la tradabilite d'un instrument avant toute analyse.

Produit des codes de rejet machine-readable distincts du texte humain affiche.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from alladin.brokers.base import BrokerAdapter
from alladin.challenge.models import UniverseRules
from alladin.market.models import ScanCandidate


class RejectCode(StrEnum):
    """Codes de rejet machine-readable -- stables entre versions."""

    NO_TICK = "NO_TICK"
    STALE_TICK = "STALE_TICK"
    INVALID_TICK = "INVALID_TICK"
    CLOCK_SKEW = "CLOCK_SKEW"
    SPREAD_TOO_HIGH = "SPREAD_TOO_HIGH"
    ATR_TOO_LOW = "ATR_TOO_LOW"
    ATR_UNAVAILABLE = "ATR_UNAVAILABLE"
    INVALID_SPEC = "INVALID_SPEC"
    SYMBOL_NOT_SELECTABLE = "SYMBOL_NOT_SELECTABLE"
    MARKET_CLOSED = "MARKET_CLOSED"
    INSUFFICIENT_BARS = "INSUFFICIENT_BARS"
    REGIME_UNTRADABLE = "REGIME_UNTRADABLE"
    SIZING_IMPOSSIBLE = "SIZING_IMPOSSIBLE"


@dataclass
class QualityReport:
    """Resultat de l'evaluation de qualite pour un instrument."""

    symbol: str
    passed: bool
    reject_codes: list[RejectCode] = field(default_factory=list)
    reject_reasons: list[str] = field(default_factory=list)
    spread: float | None = None
    atr: float | None = None
    spread_atr_ratio: float | None = None
    tick_age_s: float | None = None
    bars_count: int | None = None

    def reject(self, code: RejectCode, reason: str) -> None:
        self.reject_codes.append(code)
        self.reject_reasons.append(reason)
        self.passed = False


@dataclass
class MarketQualityEngine:
    """Evalue la qualite de marche avant l'analyse de regime et de strategie.

    Les codes de rejet sont machine-readable pour les Opportunity.rejection_reasons.
    """

    rules: UniverseRules
    max_tick_age_s: float = 1800.0
    min_bars: int = 60

    def evaluate(
        self,
        broker: BrokerAdapter,
        symbol: str,
        now: datetime,
        atr: float | None = None,
    ) -> QualityReport:
        report = QualityReport(symbol=symbol, passed=True)

        if not broker.select_symbol(symbol):
            report.reject(RejectCode.SYMBOL_NOT_SELECTABLE, "symbole non selectionnable")
            return report

        spec = broker.symbol_spec(symbol)
        if spec is None:
            report.reject(RejectCode.INVALID_SPEC, "specifications broker indisponibles")
            return report
        if spec.point <= 0 or spec.loss_tick_value <= 0 or spec.trade_tick_size <= 0:
            report.reject(RejectCode.INVALID_SPEC, "specifications inexploitables (tick value/size)")
            return report

        tick = broker.tick(symbol)
        if tick is None:
            report.reject(RejectCode.NO_TICK, "aucun tick disponible")
            return report
        if tick.bid <= 0 or tick.ask <= tick.bid:
            report.reject(RejectCode.INVALID_TICK, f"tick invalide (bid={tick.bid}, ask={tick.ask})")
            return report

        age = (now - tick.time).total_seconds()
        report.tick_age_s = age
        report.spread = tick.spread

        if age < -600:
            report.reject(RejectCode.CLOCK_SKEW, f"tick dans le futur ({-age:.0f}s)")
        elif age > self.max_tick_age_s:
            report.reject(RejectCode.STALE_TICK, f"tick perime ({age / 60:.0f} min)")
            return report

        if atr is not None and atr > 0:
            report.atr = atr
            ratio = tick.spread / atr
            report.spread_atr_ratio = ratio
            if ratio > self.rules.max_spread_atr_ratio:
                report.reject(
                    RejectCode.SPREAD_TOO_HIGH,
                    f"spread/ATR {ratio:.2f} > seuil {self.rules.max_spread_atr_ratio}",
                )
        elif atr is not None and atr == 0:
            report.reject(RejectCode.ATR_TOO_LOW, "ATR nul : instrument non volatile")

        return report

    def from_candidate(self, cand: ScanCandidate) -> QualityReport:
        """Construit un QualityReport depuis un ScanCandidate deja evalue."""
        atr_val = cand.metrics.get("atr", 0.0) or 0.0
        report = QualityReport(
            symbol=cand.symbol,
            passed=True,
            spread=cand.tick.spread if cand.tick else None,
            atr=atr_val,
            spread_atr_ratio=cand.spread_atr_ratio,
        )
        if cand.spread_atr_ratio > self.rules.max_spread_atr_ratio:
            report.reject(
                RejectCode.SPREAD_TOO_HIGH,
                f"spread/ATR {cand.spread_atr_ratio:.2f} > seuil {self.rules.max_spread_atr_ratio}",
            )
        return report
