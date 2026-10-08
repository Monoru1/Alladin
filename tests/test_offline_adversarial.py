"""Additional fail-closed regression cases for the offline-only modules.

All tests use synthetic data and do not touch MT5, Binance or network.
"""
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from alladin.challenge.economic_intelligence import (
    ConsensusObservation,
    EconomicRelease,
    assess_release,
)
from alladin.challenge.market_observatory import (
    Annotation,
    Candle,
    observatory_snapshot,
)
from alladin.challenge.official_signals import (
    OfficialPublication,
    OfficialSource,
    verify_publication,
)
from alladin.challenge.paper_risk_reservations import (
    PaperRiskReservations,
    ReservationConflict,
)

T = datetime(2026, 10, 8, 12, tzinfo=UTC)


def _reserve_from_process(args: tuple[str, int]) -> bool:
    path, index = args
    ledger = PaperRiskReservations(__import__("pathlib").Path(path))
    try:
        return ledger.reserve(
            reservation_id=f"process-{index}", scope="same-scope", account=f"a{index}",
            currency="USD", amount_minor=70, limit_minor=100,
        )
    except ReservationConflict:
        return False


def test_process_level_atomicity(tmp_path):
    path = tmp_path / "process.sqlite"
    PaperRiskReservations(path)
    with ProcessPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(_reserve_from_process, [(str(path), i) for i in range(6)]))
    assert outcomes.count(True) == 1
    assert PaperRiskReservations(path).used_minor(scope="same-scope", currency="USD") == 70


def test_unknown_order_outcome_stays_reserved_after_restart(tmp_path):
    path = tmp_path / "pending.sqlite"
    ledger = PaperRiskReservations(path)
    ledger.reserve(
        reservation_id="pending", scope="s", account="a",
        currency="USD", amount_minor=90, limit_minor=100,
    )
    restarted = PaperRiskReservations(path)
    assert restarted.used_minor(scope="s", currency="USD") == 90
    with pytest.raises(ReservationConflict):
        restarted.reserve(
            reservation_id="next", scope="s", account="a",
            currency="USD", amount_minor=20, limit_minor=100,
        )


def test_macro_missing_consensus_and_future_receipt():
    release = EconomicRelease(
        "cpi", "CPI", 3.0, T, T + timedelta(minutes=2), "https://example.org/release",
    )
    forecast = ConsensusObservation(
        "cpi", 2.0, T - timedelta(minutes=1), "https://example.org/consensus",
    )
    assert assess_release(release, consensus=forecast, as_of=T).status == "NOT_YET_KNOWN"
    assert assess_release(release, consensus=None, as_of=T + timedelta(minutes=3)).surprise is None


def test_official_origin_is_not_content_authenticity():
    source = OfficialSource("central", "central.example.org")
    publication = OfficialPublication(
        "central", "id1", "https://central.example.org/notice", "Unverified claim",
        T, T + timedelta(seconds=1), "STATEMENT",
    )
    assert verify_publication(
        publication, sources=(source,), as_of=T + timedelta(seconds=2),
    ) == "VERIFIED_CONFIGURED_ORIGIN"
    assert publication.content_sha256 != ""


def test_observatory_never_leaks_future_event():
    candle = Candle("EURUSD", "1m", T, T + timedelta(minutes=1), 1., 2., 0.5, 1.5, 100.)
    marker = Annotation("event", "EURUSD", T + timedelta(minutes=1), "MACRO", "News")
    before = observatory_snapshot(
        candles=(candle,), annotations=(marker,), symbol="EURUSD", timeframe="1m", as_of=T,
    )
    assert before["candles"] == []
    assert before["annotations"] == []
