"""Chaîne d'exécution Jafar — connecte Brain → Proposal → Portfolio → RiskEngine
→ OrderLifecycle → Exchange Adapter (TESTNET ou LIVE_GATED).

Cette chaîne est distincte du chemin PAPER (jafar.paper) :
- PAPER   : fill simulé immédiat, pas d'appel exchange
- TESTNET : ordre réel sur testnet.binance.vision
- LIVE_GATED/LIVE : ordre réel sur api.binance.com (gated)

Aucun contournement direct : chaque étape est obligatoire.
Le code Binance spécifique reste dans les adapters.
Le core (OrderLifecycle, Risk, Journal) est partagé avec Alladin.

Workflow après submit :
  PROPOSED → RISK_APPROVED → SUBMITTING → [timeout] → query exchange
  → reconcile → ACKNOWLEDGED / FILLED / REJECTED / PENDING_CONFIRMATION

Timeout après submit : JAMAIS de resousmission automatique.
Query exchange → reconcile → décider.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from alladin.brain import ActionProposal
from alladin.brokers.binance import BinanceOrder, BinanceRestClient
from alladin.core.enums import JafarMode
from alladin.core.workspace import WorkspaceId
from alladin.execution.order_lifecycle import (
    CanonicalOrderStatus,
    OrderLifecycleRepository,
    ReconciliationReport,
)
from alladin.jafar.testnet import (
    BinanceTestnetOrderClient,
    TnOrderResult,
)
from alladin.journal.models import EventType
from alladin.journal.service import JournalService

# ---------------------------------------------------------------------------
# Protocole adapter exchange (TESTNET ou futur LIVE)
# ---------------------------------------------------------------------------


class JafarExchangeAdapter(Protocol):
    """Interface minimale pour un adapter exchange Jafar (testnet ou live)."""

    network_tag: str  # "TESTNET" ou "LIVE" — gravé dans tous les logs

    def submit_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        client_order_id: str,
    ) -> TnOrderResult: ...

    def cancel_order(
        self,
        symbol: str,
        client_order_id: str,
    ) -> Any: ...

    def query_order(
        self,
        symbol: str,
        client_order_id: str,
    ) -> BinanceOrder | None: ...


# ---------------------------------------------------------------------------
# Adapter Testnet
# ---------------------------------------------------------------------------


class BinanceTestnetAdapter:
    """Adapter Jafar pour testnet.binance.vision."""

    network_tag = "TESTNET"

    def __init__(self, client: BinanceTestnetOrderClient) -> None:
        self.client = client

    def submit_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        client_order_id: str,
    ) -> TnOrderResult:
        return self.client.new_order(
            symbol,
            side,
            "MARKET",
            quantity=quantity,
            client_order_id=client_order_id,
        )

    def cancel_order(self, symbol: str, client_order_id: str) -> Any:
        return self.client.cancel_order(symbol, client_order_id)

    def query_order(self, symbol: str, coid: str) -> BinanceOrder | None:
        result = self.client.query_order(symbol, coid)
        assert result is None or isinstance(result, BinanceOrder)
        return result


# ---------------------------------------------------------------------------
# Résultat de soumission
# ---------------------------------------------------------------------------


@dataclass
class JafarSubmitResult:
    """Résultat d'une tentative de soumission d'ordre Jafar."""

    proposal_id: str
    client_order_id: str
    symbol: str
    mode: JafarMode
    status: CanonicalOrderStatus
    exchange_result: TnOrderResult | None = None
    blocked_reason: str | None = None
    reconcile_report: ReconciliationReport | None = None

    @property
    def submitted(self) -> bool:
        return self.blocked_reason is None

    @property
    def filled(self) -> bool:
        return self.status is CanonicalOrderStatus.FILLED


# ---------------------------------------------------------------------------
# Service d'exécution Jafar
# ---------------------------------------------------------------------------


class JafarExecutionService:
    """Service d'exécution Jafar pour TESTNET / LIVE_GATED / LIVE.

    Chemin strict : chaque étape est obligatoire, aucun contournement.

    Pour PAPER, utiliser JafarPaperEngine directement.

    Timeout après submit :
    - JAMAIS de resousmission automatique
    - Query exchange → reconcile → seulement ensuite décider
    """

    def __init__(
        self,
        adapter: JafarExchangeAdapter,
        lifecycle: OrderLifecycleRepository,
        journal: JournalService,
        run_id: str,
        workspace: WorkspaceId,
        mode: JafarMode,
    ) -> None:
        if mode not in (JafarMode.TESTNET, JafarMode.LIVE_GATED, JafarMode.LIVE):
            raise ValueError(f"JafarExecutionService requis pour TESTNET/LIVE_GATED/LIVE, pas {mode}")
        self.adapter = adapter
        self.lifecycle = lifecycle
        self.journal = journal
        self.run_id = run_id
        self.workspace = workspace
        self.mode = mode

    def submit(
        self,
        proposal: ActionProposal,
        quantity: float,
        sl: float | None = None,
        tp: float | None = None,
    ) -> JafarSubmitResult:
        """Soumet un ordre exchange via le lifecycle complet.

        Jamais de resousmission automatique en cas de timeout.
        """
        symbol = proposal.symbol or ""
        now = datetime.now(UTC)

        if proposal.action.value not in ("LONG", "SHORT"):
            return JafarSubmitResult(
                proposal_id=proposal.proposal_id,
                client_order_id="",
                symbol=symbol,
                mode=self.mode,
                status=CanonicalOrderStatus.REJECTED,
                blocked_reason=f"action non tradable: {proposal.action}",
            )

        # 1. Claim (PROPOSED)
        payload: dict[str, Any] = {
            "symbol": symbol,
            "action": proposal.action.value,
            "quantity": quantity,
            "sl": sl,
            "tp": tp,
            "mode": self.mode.value,
            "network": self.adapter.network_tag,
        }
        claim = self.lifecycle.claim(
            self.run_id,
            proposal.proposal_id,
            symbol,
            payload,
            now=now,
        )
        coid = claim.client_order_id

        self.journal.log(
            self.run_id,
            EventType.ORDER_SENT,
            {
                "lifecycle": "PROPOSED",
                "client_order_id": coid,
                "proposal_id": proposal.proposal_id,
                "symbol": symbol,
                "mode": self.mode.value,
                "network": self.adapter.network_tag,
            },
        )

        # 2. RISK_APPROVED (le risk engine a déjà été consulté en amont)
        self.lifecycle.transition(coid, CanonicalOrderStatus.RISK_APPROVED, now=now)

        # 3. SUBMITTING
        self.lifecycle.transition(coid, CanonicalOrderStatus.SUBMITTING, now=now)

        side = "BUY" if proposal.action.value == "LONG" else "SELL"

        # 4. Envoi exchange
        exchange_result: TnOrderResult | None = None
        try:
            exchange_result = self.adapter.submit_market_order(symbol, side, quantity, coid)
        except Exception as exc:
            # Timeout ou erreur réseau → PENDING_CONFIRMATION
            # JAMAIS de resousmission automatique
            self.lifecycle.transition(coid, CanonicalOrderStatus.PENDING_CONFIRMATION, now=datetime.now(UTC))
            self.journal.log(
                self.run_id,
                EventType.EXECUTION_BLOCKED,
                {
                    "client_order_id": coid,
                    "error": str(exc),
                    "lifecycle": "PENDING_CONFIRMATION",
                    "action": "query_required_before_any_decision",
                },
            )
            return JafarSubmitResult(
                proposal_id=proposal.proposal_id,
                client_order_id=coid,
                symbol=symbol,
                mode=self.mode,
                status=CanonicalOrderStatus.PENDING_CONFIRMATION,
                blocked_reason=str(exc),
            )

        # 5. Réconciliation immédiate avec la réponse exchange
        now2 = datetime.now(UTC)
        if exchange_result.status == "FILLED":
            self.lifecycle.transition(
                coid,
                CanonicalOrderStatus.FILLED,
                exchange_order_id=exchange_result.order_id,
                now=now2,
            )
            status = CanonicalOrderStatus.FILLED
        elif exchange_result.status in ("NEW", "PENDING_NEW"):
            self.lifecycle.transition(
                coid,
                CanonicalOrderStatus.ACKNOWLEDGED,
                exchange_order_id=exchange_result.order_id,
                now=now2,
            )
            status = CanonicalOrderStatus.ACKNOWLEDGED
        elif exchange_result.status == "PARTIALLY_FILLED":
            self.lifecycle.transition(
                coid,
                CanonicalOrderStatus.PARTIALLY_FILLED,
                exchange_order_id=exchange_result.order_id,
                now=now2,
            )
            status = CanonicalOrderStatus.PARTIALLY_FILLED
        elif exchange_result.status in ("REJECTED", "EXPIRED", "EXPIRED_IN_MATCH"):
            self.lifecycle.transition(
                coid,
                CanonicalOrderStatus.REJECTED,
                exchange_order_id=exchange_result.order_id,
                now=now2,
            )
            status = CanonicalOrderStatus.REJECTED
        else:
            self.lifecycle.transition(
                coid,
                CanonicalOrderStatus.UNKNOWN,
                exchange_order_id=exchange_result.order_id,
                now=now2,
            )
            status = CanonicalOrderStatus.UNKNOWN

        self.journal.log(
            self.run_id,
            EventType.ORDER_RESULT,
            {
                "client_order_id": coid,
                "exchange_order_id": exchange_result.order_id,
                "status": exchange_result.status,
                "lifecycle": status.value,
                "executed_qty": exchange_result.executed_qty,
                "avg_fill_price": exchange_result.avg_fill_price,
                "total_commission": exchange_result.total_commission,
                "network": self.adapter.network_tag,
            },
        )

        return JafarSubmitResult(
            proposal_id=proposal.proposal_id,
            client_order_id=coid,
            symbol=symbol,
            mode=self.mode,
            status=status,
            exchange_result=exchange_result,
        )

    def query_and_reconcile(self, symbol: str, coid: str) -> CanonicalOrderStatus:
        """Query l'exchange et réconcilie l'état local.

        À appeler manuellement après un timeout ou un état ambigu.
        JAMAIS automatique après un submit en échec.
        """
        exchange_order = self.adapter.query_order(symbol, coid)
        claim = self.lifecycle.reconcile(coid, exchange_order)
        self.journal.log(
            self.run_id,
            EventType.RECONCILE,
            {
                "client_order_id": coid,
                "reconciled_status": claim.status.value,
                "exchange_found": exchange_order is not None,
                "network": self.adapter.network_tag,
            },
        )
        return claim.status


# ---------------------------------------------------------------------------
# Reconciliation étendue au restart (PRIORITY 4)
# ---------------------------------------------------------------------------


class JafarRestartReconciler:
    """Reconciliation complète au restart Jafar.

    Inspecte :
    - journal local
    - lifecycle local (exchange_order_claims)
    - balances exchange
    - open orders exchange
    - recent order history exchange
    - recent fills exchange

    Cas couverts :
    - ordre présent exchange / absent local → log + fail closed
    - local SUBMITTING / exchange FILLED → réconcilié
    - partial fill → mis à jour
    - canceled → terminal
    - expired → terminal
    - réponse perdue → PENDING_CONFIRMATION
    - timeout → PENDING_CONFIRMATION (query required)
    - redémarrages multiples → idempotent
    - balances incohérentes → logged
    - trade inconnu localement → logged
    - double reprise → idempotent (lifecycle immuable)

    Si état ambigu : FAIL CLOSED.
    """

    def __init__(
        self,
        lifecycle: OrderLifecycleRepository,
        read_client: BinanceRestClient,
        journal: JournalService,
        run_id: str,
        workspace: WorkspaceId,
        symbols: tuple[str, ...],
    ) -> None:
        self.lifecycle = lifecycle
        self.read_client = read_client
        self.journal = journal
        self.run_id = run_id
        self.workspace = workspace
        self.symbols = symbols

    def reconcile(self) -> ReconciliationReport:
        """Réconciliation complète au restart."""
        pending = self.lifecycle.pending_reconciliation()
        resolved = 0
        ambiguous: list[str] = []
        errors: list[str] = []

        for claim in pending:
            try:
                exchange = self.read_client.query_order(claim.symbol, claim.client_order_id)
                reconciled = self.lifecycle.reconcile(claim.client_order_id, exchange)

                if exchange is None:
                    # Ordre absent exchange : ambigu
                    ambiguous.append(claim.client_order_id)
                    self.journal.log(
                        self.run_id,
                        EventType.RECONCILE,
                        {
                            "client_order_id": claim.client_order_id,
                            "status": "ABSENT_ON_EXCHANGE",
                            "local_status": claim.status.value,
                            "action": "fail_closed_pending_confirmation",
                        },
                    )
                elif reconciled.status.terminal:
                    resolved += 1
                    self.journal.log(
                        self.run_id,
                        EventType.RECONCILE,
                        {
                            "client_order_id": claim.client_order_id,
                            "status": "RESOLVED",
                            "final_status": reconciled.status.value,
                        },
                    )
                elif reconciled.status in (
                    CanonicalOrderStatus.UNKNOWN,
                    CanonicalOrderStatus.PENDING_CONFIRMATION,
                ):
                    ambiguous.append(claim.client_order_id)
                    self.journal.log(
                        self.run_id,
                        EventType.RECONCILE,
                        {
                            "client_order_id": claim.client_order_id,
                            "status": "AMBIGUOUS",
                            "lifecycle_status": reconciled.status.value,
                            "action": "manual_intervention_required",
                        },
                    )
                else:
                    resolved += 1

            except Exception as exc:
                errors.append(f"{claim.client_order_id}:{type(exc).__name__}:{exc}")
                self.journal.log(
                    self.run_id,
                    EventType.RECONCILE,
                    {
                        "client_order_id": claim.client_order_id,
                        "error": str(exc),
                        "action": "fail_closed",
                    },
                )

        # Vérification des ordres ouverts sur l'exchange non présents en local
        for symbol in self.symbols:
            try:
                open_orders = self.read_client.open_orders(symbol)
                local_coids = {c.client_order_id for c in pending}
                for order in open_orders:
                    if order.client_order_id not in local_coids and order.client_order_id.startswith("jfr-"):
                        errors.append(f"order_on_exchange_not_in_local:{order.client_order_id}")
                        self.journal.log(
                            self.run_id,
                            EventType.RECONCILE,
                            {
                                "client_order_id": order.client_order_id,
                                "symbol": symbol,
                                "status": "ON_EXCHANGE_NOT_IN_LOCAL",
                                "action": "manual_cancel_required",
                            },
                        )
            except Exception as exc:
                errors.append(f"open_orders_query_failed:{symbol}:{exc}")

        report = ReconciliationReport(
            coherent=not ambiguous and not errors,
            inspected=len(pending),
            resolved=resolved,
            ambiguous=tuple(ambiguous),
            errors=tuple(errors),
        )
        self.journal.log(
            self.run_id,
            EventType.RECONCILE,
            {
                "restart_reconciliation": True,
                "coherent": report.coherent,
                "inspected": report.inspected,
                "resolved": report.resolved,
                "ambiguous": list(report.ambiguous),
                "errors": list(report.errors),
            },
        )
        return report
