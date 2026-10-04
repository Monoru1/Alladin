"""Cycle de vie canonique des futurs ordres exchange, sans fonction d'envoi.

Le registre persiste l'intention avant toute soumission future. Un etat ambigu
reste PENDING_CONFIRMATION et ne peut jamais redevenir SUBMITTING.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Column, MetaData, String, Table, Text, UniqueConstraint
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from alladin.brokers.binance import BinanceOrder
from alladin.core.workspace import WorkspaceId


class OrderLifecycleError(ValueError):
    pass


class CanonicalOrderStatus(StrEnum):
    PROPOSED = "PROPOSED"
    RISK_APPROVED = "RISK_APPROVED"
    SUBMITTING = "SUBMITTING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELED = "CANCELED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"

    @property
    def terminal(self) -> bool:
        return self in {
            CanonicalOrderStatus.FILLED,
            CanonicalOrderStatus.REJECTED,
            CanonicalOrderStatus.CANCELED,
            CanonicalOrderStatus.EXPIRED,
        }


_TRANSITIONS: dict[CanonicalOrderStatus, frozenset[CanonicalOrderStatus]] = {
    CanonicalOrderStatus.PROPOSED: frozenset(
        {CanonicalOrderStatus.RISK_APPROVED, CanonicalOrderStatus.REJECTED}
    ),
    CanonicalOrderStatus.RISK_APPROVED: frozenset(
        {CanonicalOrderStatus.SUBMITTING, CanonicalOrderStatus.REJECTED}
    ),
    CanonicalOrderStatus.SUBMITTING: frozenset(
        {
            CanonicalOrderStatus.ACKNOWLEDGED,
            CanonicalOrderStatus.PARTIALLY_FILLED,
            CanonicalOrderStatus.FILLED,
            CanonicalOrderStatus.REJECTED,
            CanonicalOrderStatus.PENDING_CONFIRMATION,
            CanonicalOrderStatus.UNKNOWN,
        }
    ),
    CanonicalOrderStatus.PENDING_CONFIRMATION: frozenset(
        {
            CanonicalOrderStatus.ACKNOWLEDGED,
            CanonicalOrderStatus.PARTIALLY_FILLED,
            CanonicalOrderStatus.FILLED,
            CanonicalOrderStatus.REJECTED,
            CanonicalOrderStatus.CANCELED,
            CanonicalOrderStatus.EXPIRED,
            CanonicalOrderStatus.UNKNOWN,
        }
    ),
    CanonicalOrderStatus.UNKNOWN: frozenset(
        {
            CanonicalOrderStatus.ACKNOWLEDGED,
            CanonicalOrderStatus.PARTIALLY_FILLED,
            CanonicalOrderStatus.FILLED,
            CanonicalOrderStatus.REJECTED,
            CanonicalOrderStatus.CANCELED,
            CanonicalOrderStatus.EXPIRED,
            CanonicalOrderStatus.PENDING_CONFIRMATION,
        }
    ),
    CanonicalOrderStatus.ACKNOWLEDGED: frozenset(
        {
            CanonicalOrderStatus.PARTIALLY_FILLED,
            CanonicalOrderStatus.FILLED,
            CanonicalOrderStatus.CANCELED,
            CanonicalOrderStatus.EXPIRED,
            CanonicalOrderStatus.UNKNOWN,
        }
    ),
    CanonicalOrderStatus.PARTIALLY_FILLED: frozenset(
        {
            CanonicalOrderStatus.PARTIALLY_FILLED,
            CanonicalOrderStatus.FILLED,
            CanonicalOrderStatus.CANCELED,
            CanonicalOrderStatus.EXPIRED,
            CanonicalOrderStatus.UNKNOWN,
        }
    ),
}


class OrderClaim(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    workspace: WorkspaceId
    run_id: str = Field(min_length=1)
    proposal_id: str = Field(min_length=1)
    client_order_id: str = Field(min_length=1, max_length=36)
    symbol: str = Field(min_length=1)
    payload: dict[str, Any]
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: CanonicalOrderStatus
    exchange_order_id: int | None = None
    created_at: datetime
    updated_at: datetime


_meta = MetaData()
order_claims = Table(
    "exchange_order_claims",
    _meta,
    Column("workspace", String, nullable=False),
    Column("run_id", String, nullable=False),
    Column("proposal_id", String, nullable=False),
    Column("client_order_id", String, primary_key=True),
    Column("symbol", String, nullable=False),
    Column("payload", Text, nullable=False),
    Column("fingerprint", String, nullable=False),
    Column("status", String, nullable=False),
    Column("exchange_order_id", String),
    Column("created_at", String, nullable=False),
    Column("updated_at", String, nullable=False),
    UniqueConstraint("workspace", "run_id", "proposal_id", name="uq_exchange_order_proposal"),
)


def client_order_id(workspace: WorkspaceId, run_id: str, proposal_id: str) -> str:
    digest = hashlib.sha256(f"{workspace.value}|{run_id}|{proposal_id}".encode()).hexdigest()[:28]
    return f"jfr-{digest}"


def _canon(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


class OrderLifecycleRepository:
    def __init__(self, engine: Engine, workspace: WorkspaceId) -> None:
        self.engine = engine
        self.workspace = WorkspaceId(workspace)
        _meta.create_all(engine)

    def claim(
        self,
        run_id: str,
        proposal_id: str,
        symbol: str,
        payload: dict[str, Any],
        *,
        now: datetime | None = None,
    ) -> OrderClaim:
        now = (now or datetime.now(UTC)).astimezone(UTC)
        body = _canon(payload)
        fingerprint = hashlib.sha256(body.encode()).hexdigest()
        order_id = client_order_id(self.workspace, run_id, proposal_id)
        values = dict(
            workspace=self.workspace.value,
            run_id=run_id,
            proposal_id=proposal_id,
            client_order_id=order_id,
            symbol=symbol,
            payload=body,
            fingerprint=fingerprint,
            status=CanonicalOrderStatus.PROPOSED.value,
            exchange_order_id=None,
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
        )
        try:
            with self.engine.begin() as connection:
                connection.execute(order_claims.insert().values(**values))
        except IntegrityError:
            existing = self.get_by_proposal(run_id, proposal_id)
            if existing is None or existing.fingerprint != fingerprint or existing.symbol != symbol:
                raise OrderLifecycleError(
                    "proposal_id/clientOrderId reutilise avec un contenu different"
                ) from None
            return existing
        return self._model(values)

    def get(self, order_id: str) -> OrderClaim | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    order_claims.select().where(
                        order_claims.c.client_order_id == order_id,
                        order_claims.c.workspace == self.workspace.value,
                    )
                )
                .mappings()
                .first()
            )
        return self._model(dict(row)) if row else None

    def get_by_proposal(self, run_id: str, proposal_id: str) -> OrderClaim | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    order_claims.select().where(
                        order_claims.c.workspace == self.workspace.value,
                        order_claims.c.run_id == run_id,
                        order_claims.c.proposal_id == proposal_id,
                    )
                )
                .mappings()
                .first()
            )
        return self._model(dict(row)) if row else None

    def transition(
        self,
        order_id: str,
        target: CanonicalOrderStatus,
        *,
        exchange_order_id: int | None = None,
        now: datetime | None = None,
    ) -> OrderClaim:
        current = self.get(order_id)
        if current is None:
            raise OrderLifecycleError("ordre inconnu")
        allowed = _TRANSITIONS.get(current.status, frozenset())
        if target not in allowed:
            raise OrderLifecycleError(f"transition interdite: {current.status.value}->{target.value}")
        if (
            current.status in {CanonicalOrderStatus.PENDING_CONFIRMATION, CanonicalOrderStatus.UNKNOWN}
            and target is CanonicalOrderStatus.SUBMITTING
        ):
            raise OrderLifecycleError("un ordre ambigu ne peut jamais etre resoumis")
        timestamp = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
        with self.engine.begin() as connection:
            updated = connection.execute(
                order_claims.update()
                .where(
                    order_claims.c.client_order_id == order_id,
                    order_claims.c.workspace == self.workspace.value,
                    order_claims.c.status == current.status.value,
                )
                .values(
                    status=target.value,
                    updated_at=timestamp,
                    exchange_order_id=str(exchange_order_id)
                    if exchange_order_id is not None
                    else (str(current.exchange_order_id) if current.exchange_order_id is not None else None),
                )
            )
            if updated.rowcount != 1:
                raise OrderLifecycleError("ordre modifie concurremment")
        result = self.get(order_id)
        assert result is not None
        return result

    def reconcile(self, order_id: str, exchange: BinanceOrder | None) -> OrderClaim:
        current = self.get(order_id)
        if current is None:
            raise OrderLifecycleError("ordre inconnu")
        if current.status not in {
            CanonicalOrderStatus.SUBMITTING,
            CanonicalOrderStatus.PENDING_CONFIRMATION,
            CanonicalOrderStatus.UNKNOWN,
            CanonicalOrderStatus.ACKNOWLEDGED,
            CanonicalOrderStatus.PARTIALLY_FILLED,
        }:
            raise OrderLifecycleError("ordre non reconciliable")
        if exchange is None:
            if current.status is CanonicalOrderStatus.SUBMITTING:
                return self.transition(order_id, CanonicalOrderStatus.PENDING_CONFIRMATION)
            return current
        if exchange.client_order_id != order_id or exchange.symbol != current.symbol:
            raise OrderLifecycleError("identite exchange incoherente: fail closed")
        mapping = {
            "NEW": CanonicalOrderStatus.ACKNOWLEDGED,
            "PENDING_NEW": CanonicalOrderStatus.ACKNOWLEDGED,
            "PARTIALLY_FILLED": CanonicalOrderStatus.PARTIALLY_FILLED,
            "FILLED": CanonicalOrderStatus.FILLED,
            "CANCELED": CanonicalOrderStatus.CANCELED,
            "EXPIRED": CanonicalOrderStatus.EXPIRED,
            "EXPIRED_IN_MATCH": CanonicalOrderStatus.EXPIRED,
            "REJECTED": CanonicalOrderStatus.REJECTED,
        }
        target = mapping.get(exchange.status, CanonicalOrderStatus.UNKNOWN)
        if target == current.status:
            return current
        return self.transition(order_id, target, exchange_order_id=exchange.order_id)

    def pending_reconciliation(self) -> tuple[OrderClaim, ...]:
        states = (
            CanonicalOrderStatus.SUBMITTING.value,
            CanonicalOrderStatus.PENDING_CONFIRMATION.value,
            CanonicalOrderStatus.UNKNOWN.value,
        )
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    order_claims.select().where(
                        order_claims.c.workspace == self.workspace.value, order_claims.c.status.in_(states)
                    )
                )
                .mappings()
                .all()
            )
        return tuple(self._model(dict(row)) for row in rows)

    @staticmethod
    def _model(row: dict[str, Any]) -> OrderClaim:
        return OrderClaim(
            workspace=row["workspace"],
            run_id=row["run_id"],
            proposal_id=row["proposal_id"],
            client_order_id=row["client_order_id"],
            symbol=row["symbol"],
            payload=json.loads(row["payload"]),
            fingerprint=row["fingerprint"],
            status=row["status"],
            exchange_order_id=int(row["exchange_order_id"])
            if row.get("exchange_order_id") is not None
            else None,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
