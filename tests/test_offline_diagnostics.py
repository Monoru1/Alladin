"""Offline integration tests for diagnostic-only composition."""
from datetime import UTC, datetime

from alladin.challenge.offline_diagnostics import OfflineDiagnosticInput, offline_diagnostic
from alladin.challenge.paper_reconciliation import PaperSnapshot
from alladin.challenge.paper_risk_reservations import PaperRiskReservations

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)


def request(**changes):
    values = dict(
        as_of=NOW, initial=PaperSnapshot(1000, {}), observed=PaperSnapshot(1000, {}),
        fills=(), complete_ledger=True, scope="phase1", currency="USD",
        risk_limit_minor=500, symbol="EURUSD", timeframe="1m",
    )
    values.update(changes)
    return OfflineDiagnosticInput(**values)


def test_passive_integration_never_authorizes_execution(tmp_path):
    ledger = PaperRiskReservations(tmp_path / "risk.sqlite")
    result = offline_diagnostic(request(), reservations=ledger)
    assert result["diagnostic_only"] is True
    assert result["execution_authorized"] is False
    assert result["paper_consistent"] is True
    assert result["chart"]["candles"] == []


def test_incomplete_paper_journal_blocks_diagnostic(tmp_path):
    ledger = PaperRiskReservations(tmp_path / "risk.sqlite")
    result = offline_diagnostic(request(complete_ledger=False), reservations=ledger)
    assert result["paper_consistent"] is False
    assert "PAPER_RECONCILIATION_FAILED" in result["blockers"]
    assert result["execution_authorized"] is False


def test_excess_reserved_risk_is_visible(tmp_path):
    ledger = PaperRiskReservations(tmp_path / "risk.sqlite")
    ledger.reserve(reservation_id="r1", scope="phase1", account="a",
                   currency="USD", amount_minor=400, limit_minor=500)
    result = offline_diagnostic(request(risk_limit_minor=300), reservations=ledger)
    assert "PAPER_RESERVED_RISK_OVER_LIMIT" in result["blockers"]
    assert result["risk_used_minor"] == 400
