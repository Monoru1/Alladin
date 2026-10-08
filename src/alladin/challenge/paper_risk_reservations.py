"""Conservative cross-process PAPER risk reservation ledger (not wired to execution).

SQLite BEGIN IMMEDIATE serializes competing writers. Unknown order outcomes remain
reserved until reconciliation; never infer broker cancellation from a timeout.
Amounts use integer minor units supplied in one explicitly named currency.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path


class ReservationConflict(ValueError):
    """Fail closed when a reservation cannot safely be accepted."""


class PaperRiskReservations:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS paper_risk_reservations (
                reservation_id TEXT PRIMARY KEY,
                scope TEXT NOT NULL,
                account TEXT NOT NULL,
                currency TEXT NOT NULL,
                amount_minor INTEGER NOT NULL CHECK(amount_minor > 0),
                state TEXT NOT NULL CHECK(state IN ('RESERVED','COMMITTED','RELEASED'))
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS risk_scope_idx ON paper_risk_reservations(scope,currency,state)")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def reserve(
        self, *, reservation_id: str, scope: str, account: str,
        currency: str, amount_minor: int, limit_minor: int,
    ) -> bool:
        """Return True on new reservation, False on identical retry.

        All amounts are integer minor units. Scope MUST identify a complete
        account group and policy phase; caller must supply an independently
        verified limit. This is not a trading authorization.
        """
        if not all(isinstance(v, str) and v.strip() == v and v for v in
                   (reservation_id, scope, account, currency)):
            raise ReservationConflict("explicit nonempty identifiers required")
        if type(amount_minor) is not int or type(limit_minor) is not int or amount_minor <= 0 or limit_minor < 0:
            raise ReservationConflict("integer minor units and nonnegative limit required")
        with self._connect() as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                prior = db.execute(
                    "SELECT * FROM paper_risk_reservations WHERE reservation_id=?", (reservation_id,)
                ).fetchone()
                if prior is not None:
                    expected = (scope, account, currency, amount_minor)
                    actual = (prior["scope"], prior["account"], prior["currency"], prior["amount_minor"])
                    if expected != actual or prior["state"] == "RELEASED":
                        raise ReservationConflict("conflicting or released idempotency key")
                    # A retry cannot bypass a newly lowered budget.
                    total = db.execute(
                        "SELECT COALESCE(SUM(amount_minor),0) FROM paper_risk_reservations "
                        "WHERE scope=? AND currency=? AND state!='RELEASED'", (scope, currency)
                    ).fetchone()[0]
                    if total > limit_minor:
                        raise ReservationConflict("scope over current limit")
                    db.execute("COMMIT")
                    return False
                total = db.execute(
                    "SELECT COALESCE(SUM(amount_minor),0) FROM paper_risk_reservations "
                    "WHERE scope=? AND currency=? AND state!='RELEASED'", (scope, currency)
                ).fetchone()[0]
                if total + amount_minor > limit_minor:
                    raise ReservationConflict("insufficient reserved risk capacity")
                db.execute(
                    "INSERT INTO paper_risk_reservations VALUES (?,?,?,?,?, 'RESERVED')",
                    (reservation_id, scope, account, currency, amount_minor),
                )
                db.execute("COMMIT")
                return True
            except BaseException:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise

    def commit(self, reservation_id: str) -> None:
        """Mark accepted exposure; still consumes capacity until reconciled."""
        with self._connect() as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT state FROM paper_risk_reservations WHERE reservation_id=?",
                                 (reservation_id,)).fetchone()
                if row is None or row["state"] == "RELEASED":
                    raise ReservationConflict("missing or released reservation")
                db.execute("UPDATE paper_risk_reservations SET state='COMMITTED' WHERE reservation_id=?",
                           (reservation_id,))
                db.execute("COMMIT")
            except BaseException:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise

    def release_verified(self, reservation_id: str, *, reconciliation_confirmed: bool) -> None:
        """Caller must prove no live/pending exposure remains before release."""
        if reconciliation_confirmed is not True:
            raise ReservationConflict("verified reconciliation required to release")
        with self._connect() as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT state FROM paper_risk_reservations WHERE reservation_id=?",
                                 (reservation_id,)).fetchone()
                if row is None:
                    raise ReservationConflict("unknown reservation")
                db.execute("UPDATE paper_risk_reservations SET state='RELEASED' WHERE reservation_id=?",
                           (reservation_id,))
                db.execute("COMMIT")
            except BaseException:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise

    def used_minor(self, *, scope: str, currency: str) -> int:
        with self._connect() as db:
            return int(db.execute(
                "SELECT COALESCE(SUM(amount_minor),0) FROM paper_risk_reservations "
                "WHERE scope=? AND currency=? AND state!='RELEASED'", (scope, currency)
            ).fetchone()[0])
