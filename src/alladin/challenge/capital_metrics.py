"""Capital versus simulated allocation accounting (DECISION-034)."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class CapitalLedger:
    simulated_allocation: float
    evaluation_fees_paid: float
    payouts_received: float
    operating_costs_paid: float
    taxes_paid: float

    def __post_init__(self) -> None:
        amounts = (
            self.simulated_allocation,
            self.evaluation_fees_paid,
            self.payouts_received,
            self.operating_costs_paid,
            self.taxes_paid,
        )
        if any(not isfinite(value) or value < 0 for value in amounts):
            raise ValueError("ledger amounts must be finite and nonnegative")

    @property
    def net_cash_generated(self) -> float:
        """Realized cash only, NOT simulated profits or nominal allocation."""
        return (self.payouts_received - self.evaluation_fees_paid
                - self.operating_costs_paid - self.taxes_paid)

    @property
    def payout_to_fee_ratio(self) -> float | None:
        return (self.payouts_received / self.evaluation_fees_paid
                if self.evaluation_fees_paid > 0 else None)
