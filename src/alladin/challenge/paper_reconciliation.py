"""Offline PAPER portfolio reconciliation; never queries a broker or authorizes trades.

Amounts use integer minor units. Callers must supply a complete authoritative
snapshot and independently verified event ledger. Missing events fail closed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class PaperFill:
    event_id: str
    symbol: str
    side: Literal["BUY", "SELL"]
    quantity_units: int
    cash_minor: int
    fee_minor: int = 0

    def __post_init__(self) -> None:
        if (not self.event_id or not self.symbol or self.side not in ("BUY", "SELL")
                or type(self.quantity_units) is not int or self.quantity_units <= 0
                or type(self.cash_minor) is not int or self.cash_minor < 0
                or type(self.fee_minor) is not int or self.fee_minor < 0):
            raise ValueError("invalid PAPER fill")


@dataclass(frozen=True)
class PaperSnapshot:
    cash_minor: int
    positions_units: dict[str, int]

    def __post_init__(self) -> None:
        if type(self.cash_minor) is not int or any(
            not symbol or type(quantity) is not int for symbol, quantity in self.positions_units.items()
        ):
            raise ValueError("invalid PAPER snapshot")


@dataclass(frozen=True)
class PaperReconciliation:
    consistent: bool
    expected: PaperSnapshot
    observed: PaperSnapshot
    discrepancies: tuple[str, ...]


def reconcile_paper(
    *, initial: PaperSnapshot, fills: tuple[PaperFill, ...],
    observed: PaperSnapshot, complete_ledger: bool,
) -> PaperReconciliation:
    """Compare independently observed state to replayed fills, without repair.

    cash_minor is the total absolute notional transferred per fill, not a price.
    A BUY consumes notional + fees; a SELL credits notional - fees.
    Signed positions support shorts. An incomplete ledger is never green.
    """
    cash = initial.cash_minor
    positions = dict(initial.positions_units)
    seen: set[str] = set()
    discrepancies: list[str] = []
    if not complete_ledger:
        discrepancies.append("LEDGER_INCOMPLETE")
    for fill in fills:
        if fill.event_id in seen:
            discrepancies.append(f"DUPLICATE_EVENT:{fill.event_id}")
            continue
        seen.add(fill.event_id)
        direction = 1 if fill.side == "BUY" else -1
        positions[fill.symbol] = positions.get(fill.symbol, 0) + direction * fill.quantity_units
        cash -= direction * fill.cash_minor + fill.fee_minor
    expected = PaperSnapshot(cash_minor=cash, positions_units={
        symbol: quantity for symbol, quantity in positions.items() if quantity != 0
    })
    actual_positions = {symbol: quantity for symbol, quantity in observed.positions_units.items() if quantity != 0}
    if expected.cash_minor != observed.cash_minor:
        discrepancies.append("CASH_MISMATCH")
    for symbol in sorted(set(expected.positions_units) | set(actual_positions)):
        if expected.positions_units.get(symbol, 0) != actual_positions.get(symbol, 0):
            discrepancies.append(f"POSITION_MISMATCH:{symbol}")
    return PaperReconciliation(
        consistent=not discrepancies, expected=expected, observed=observed,
        discrepancies=tuple(discrepancies),
    )
