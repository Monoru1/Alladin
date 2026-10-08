"""Offline-only integration of policy evidence, PAPER reconciliation and observatory.

This is a diagnostic read model, NOT an execution gate or broker adapter.
The runtime must explicitly integrate and validate it before relying on it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from alladin.challenge.economic_intelligence import (
    ConsensusObservation, EconomicRelease, assess_release,
)
from alladin.challenge.market_observatory import (
    Annotation, Candle, observatory_snapshot,
)
from alladin.challenge.official_signals import (
    OfficialPublication, OfficialSource, verify_publication,
)
from alladin.challenge.paper_reconciliation import (
    PaperFill, PaperSnapshot, reconcile_paper,
)
from alladin.challenge.paper_risk_reservations import PaperRiskReservations


@dataclass(frozen=True)
class OfflineDiagnosticInput:
    as_of: datetime
    initial: PaperSnapshot
    observed: PaperSnapshot
    fills: tuple[PaperFill, ...]
    complete_ledger: bool
    scope: str
    currency: str
    risk_limit_minor: int
    symbol: str
    timeframe: str
    candles: tuple[Candle, ...] = ()
    annotations: tuple[Annotation, ...] = ()
    releases: tuple[EconomicRelease, ...] = ()
    consensuses: tuple[ConsensusObservation, ...] = ()
    publications: tuple[OfficialPublication, ...] = ()
    sources: tuple[OfficialSource, ...] = ()


def offline_diagnostic(
    request: OfflineDiagnosticInput, *, reservations: PaperRiskReservations,
) -> dict[str, object]:
    """Return evidence with explicit blockers, never a permission to place orders."""
    reconciliation = reconcile_paper(
        initial=request.initial, observed=request.observed, fills=request.fills,
        complete_ledger=request.complete_ledger,
    )
    used = reservations.used_minor(scope=request.scope, currency=request.currency)
    if type(request.risk_limit_minor) is not int or request.risk_limit_minor < 0:
        raise ValueError("nonnegative integer risk limit required")
    economic = [
        assess_release(
            release,
            consensus=next((c for c in request.consensuses if c.event_id == release.event_id), None),
            as_of=request.as_of,
        )
        for release in request.releases
    ]
    official = [
        {"id": publication.publication_id,
         "status": verify_publication(publication, sources=request.sources, as_of=request.as_of)}
        for publication in request.publications
    ]
    blockers = []
    if not reconciliation.consistent:
        blockers.append("PAPER_RECONCILIATION_FAILED")
    if used > request.risk_limit_minor:
        blockers.append("PAPER_RESERVED_RISK_OVER_LIMIT")
    if any(item.status != "OBSERVED_SURPRISE" for item in economic):
        blockers.append("ECONOMIC_EVIDENCE_INCOMPLETE")
    if any(item["status"] != "VERIFIED_CONFIGURED_ORIGIN" for item in official):
        blockers.append("OFFICIAL_EVIDENCE_UNVERIFIED")
    chart = observatory_snapshot(
        candles=request.candles, annotations=request.annotations,
        symbol=request.symbol, timeframe=request.timeframe, as_of=request.as_of,
    )
    return {
        "diagnostic_only": True,
        "execution_authorized": False,
        "paper_consistent": reconciliation.consistent,
        "paper_discrepancies": list(reconciliation.discrepancies),
        "risk_used_minor": used,
        "risk_limit_minor": request.risk_limit_minor,
        "economic": [
            {"id": item.event_id, "status": item.status,
             "surprise": item.surprise, "relative_surprise": item.relative_surprise}
            for item in economic
        ],
        "official": official,
        "chart": chart,
        "blockers": blockers,
    }
