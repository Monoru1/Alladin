"""Offline tests: deterministic PAPER fill replay, no MT5 terminal."""
from alladin.challenge.paper_reconciliation import (
    PaperFill,
    PaperSnapshot,
    reconcile_paper,
)


def test_partial_exit_and_fees_reconcile():
    initial = PaperSnapshot(cash_minor=1_000_000, positions_units={})
    fills = (
        PaperFill("buy", "BTC", "BUY", 10, 600_000, 600),
        PaperFill("partial", "BTC", "SELL", 4, 244_000, 244),
    )
    observed = PaperSnapshot(cash_minor=643_156, positions_units={"BTC": 6})
    result = reconcile_paper(initial=initial, fills=fills, observed=observed, complete_ledger=True)
    assert result.consistent
    assert result.expected == observed


def test_duplicate_events_never_count_as_consistent():
    initial = PaperSnapshot(cash_minor=1000, positions_units={})
    fill = PaperFill("same", "EURUSD", "BUY", 1, 100)
    observed = PaperSnapshot(cash_minor=900, positions_units={"EURUSD": 1})
    result = reconcile_paper(initial=initial, fills=(fill, fill), observed=observed, complete_ledger=True)
    assert not result.consistent
    assert "DUPLICATE_EVENT:same" in result.discrepancies


def test_incomplete_ledger_fails_closed_even_if_balances_match():
    initial = PaperSnapshot(cash_minor=1000, positions_units={})
    result = reconcile_paper(initial=initial, fills=(), observed=initial, complete_ledger=False)
    assert not result.consistent
    assert result.discrepancies == ("LEDGER_INCOMPLETE",)


def test_position_and_cash_divergence():
    initial = PaperSnapshot(cash_minor=1000, positions_units={})
    fill = PaperFill("buy", "EURUSD", "BUY", 2, 100)
    observed = PaperSnapshot(cash_minor=901, positions_units={"EURUSD": 1})
    result = reconcile_paper(initial=initial, fills=(fill,), observed=observed, complete_ledger=True)
    assert result.discrepancies == ("CASH_MISMATCH", "POSITION_MISMATCH:EURUSD")
