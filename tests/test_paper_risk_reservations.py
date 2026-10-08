"""Offline-only tests for atomic PAPER reservation ledger."""
from concurrent.futures import ThreadPoolExecutor

import pytest

from alladin.challenge.paper_risk_reservations import PaperRiskReservations, ReservationConflict


def test_atomic_competition(tmp_path):
    path = tmp_path / "risk.sqlite"

    def attempt(i):
        ledger = PaperRiskReservations(path)
        try:
            return ledger.reserve(reservation_id=f"r{i}", scope="phase1", account=f"a{i}",
                                  currency="USD", amount_minor=400, limit_minor=600)
        except ReservationConflict:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(8)))
    assert sum(results) == 1
    assert PaperRiskReservations(path).used_minor(scope="phase1", currency="USD") == 400


def test_retry_restart_commit_and_verified_release(tmp_path):
    path = tmp_path / "risk.sqlite"
    a = PaperRiskReservations(path)
    args = dict(reservation_id="r1", scope="phase1", account="a", currency="USD",
                amount_minor=400, limit_minor=600)
    assert a.reserve(**args) is True
    b = PaperRiskReservations(path)
    assert b.reserve(**args) is False
    b.commit("r1")
    assert b.reserve(**args) is False
    with pytest.raises(ReservationConflict):
        b.reserve(**{**args, "amount_minor": 500})
    with pytest.raises(ReservationConflict):
        b.release_verified("r1", reconciliation_confirmed=False)
    assert b.used_minor(scope="phase1", currency="USD") == 400
    b.release_verified("r1", reconciliation_confirmed=True)
    assert b.used_minor(scope="phase1", currency="USD") == 0
    with pytest.raises(ReservationConflict):
        b.reserve(**args)


def test_scope_currency_and_limits_fail_closed(tmp_path):
    ledger = PaperRiskReservations(tmp_path / "risk.sqlite")
    base = dict(scope="phase1", account="a", currency="USD", amount_minor=400, limit_minor=600)
    assert ledger.reserve(reservation_id="r1", **base)
    with pytest.raises(ReservationConflict):
        ledger.reserve(reservation_id="r2", **base)
    with pytest.raises(ReservationConflict):
        ledger.reserve(reservation_id="r1", **{**base, "limit_minor": 300})
    with pytest.raises(ReservationConflict):
        ledger.reserve(reservation_id="r3", **{**base, "amount_minor": True})
    assert ledger.reserve(reservation_id="r4", **{**base, "scope": "phase2"})
    assert ledger.reserve(reservation_id="r5", **{**base, "currency": "EUR"})
