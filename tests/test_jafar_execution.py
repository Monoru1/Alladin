"""Tests chaîne d'exécution Jafar — mocks uniquement, aucun réseau."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from alladin.brain import Action, ActionProposal, proposal_identity
from alladin.brokers.binance import BinanceOrder
from alladin.core.enums import JafarMode
from alladin.core.workspace import WorkspaceId
from alladin.execution.order_lifecycle import (
    CanonicalOrderStatus,
    OrderLifecycleRepository,
)
from alladin.jafar.execution import (
    JafarExecutionService,
    JafarRestartReconciler,
)
from alladin.jafar.testnet import TnFill, TnOrderResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime(2026, 10, 4, 18, 0, 0, tzinfo=UTC)


def _proposal(action: str = "LONG") -> ActionProposal:
    from alladin.brain import ProposalParameters
    from alladin.core.enums import EntryType, MarketRegime

    run_id = "RUN-JAFAR-EXEC"
    cycle_id = "CYC-001"
    opp_id = "OPP-001"
    pid = proposal_identity(run_id, cycle_id, opp_id, "jafar:exec:test", "1")
    return ActionProposal(
        proposal_id=pid,
        source_id="jafar:exec:test",
        source_version="1",
        run_id=run_id,
        cycle_id=cycle_id,
        opportunity_id=opp_id,
        symbol="BTCUSDT",
        action=Action(action),
        timestamp=_now(),
        parameters=ProposalParameters(
            strategy_id="test",
            strategy_version="1",
            market_regime=MarketRegime.TREND,
            entry_type=EntryType.MARKET,
            requested_risk_pct_of_working_capital=1.0,
        ),
    )


def _filled_result(client_order_id: str = "jfr-abc123") -> TnOrderResult:
    fill = TnFill(price=65_000.0, qty=0.001, commission=0.065, commission_asset="USDT")
    return TnOrderResult(
        symbol="BTCUSDT",
        order_id=12345,
        client_order_id=client_order_id,
        transact_time=_now(),
        price=0.0,
        original_qty=0.001,
        executed_qty=0.001,
        status="FILLED",
        side="BUY",
        order_type="MARKET",
        fills=(fill,),
    )


def _mock_lifecycle(run_id: str = "RUN-JAFAR-EXEC") -> MagicMock:
    from sqlalchemy import create_engine

    engine_db = create_engine("sqlite:///:memory:")
    workspace = WorkspaceId.JAFAR
    repo = OrderLifecycleRepository(engine_db, workspace)
    return repo


def _mock_journal() -> MagicMock:
    journal = MagicMock()
    journal.log = MagicMock()
    return journal


def _mock_adapter(filled: bool = True) -> MagicMock:
    adapter = MagicMock()
    adapter.network_tag = "TESTNET"
    if filled:
        adapter.submit_market_order.return_value = _filled_result()
    else:
        adapter.submit_market_order.side_effect = RuntimeError("network timeout")
    return adapter


# ---------------------------------------------------------------------------
# JafarExecutionService
# ---------------------------------------------------------------------------


class TestJafarExecutionService:
    def _service(self, adapter=None, filled=True) -> tuple[JafarExecutionService, MagicMock]:
        adapter = adapter or _mock_adapter(filled=filled)
        lifecycle = _mock_lifecycle()
        journal = _mock_journal()
        service = JafarExecutionService(
            adapter=adapter,
            lifecycle=lifecycle,
            journal=journal,
            run_id="RUN-JAFAR-EXEC",
            workspace=WorkspaceId.JAFAR,
            mode=JafarMode.TESTNET,
        )
        return service, adapter

    def test_submit_filled_order(self) -> None:
        service, adapter = self._service()
        proposal = _proposal("LONG")
        result = service.submit(proposal, quantity=0.001)
        assert result.submitted
        assert result.filled
        assert result.status is CanonicalOrderStatus.FILLED
        assert result.client_order_id.startswith("jfr-")

    def test_submit_sell_order(self) -> None:
        adapter = _mock_adapter(filled=True)
        adapter.submit_market_order.return_value = TnOrderResult(
            symbol="BTCUSDT",
            order_id=99999,
            client_order_id="jfr-abc",
            transact_time=_now(),
            price=0.0,
            original_qty=0.001,
            executed_qty=0.001,
            status="FILLED",
            side="SELL",
            order_type="MARKET",
            fills=(TnFill(65_000.0, 0.001, 0.065, "USDT"),),
        )
        service, _ = self._service(adapter=adapter)
        proposal = _proposal("SHORT")
        result = service.submit(proposal, quantity=0.001)
        assert result.filled

    def test_network_timeout_gives_pending_confirmation(self) -> None:
        service, adapter = self._service(filled=False)
        proposal = _proposal("LONG")
        result = service.submit(proposal, quantity=0.001)
        assert not result.filled
        assert result.status is CanonicalOrderStatus.PENDING_CONFIRMATION
        assert result.blocked_reason is not None

    def test_lifecycle_transitions_on_success(self) -> None:
        service, adapter = self._service()
        proposal = _proposal("LONG")
        service.submit(proposal, quantity=0.001)
        # Vérifier que le claim est dans l'état FILLED
        from alladin.execution.order_lifecycle import client_order_id as coid_fn
        coid = coid_fn(WorkspaceId.JAFAR, "RUN-JAFAR-EXEC", proposal.proposal_id)
        claim = service.lifecycle.get(coid)
        assert claim is not None
        assert claim.status is CanonicalOrderStatus.FILLED

    def test_invalid_mode_raises(self) -> None:
        with pytest.raises(ValueError, match="TESTNET/LIVE_GATED/LIVE"):
            JafarExecutionService(
                adapter=_mock_adapter(),
                lifecycle=_mock_lifecycle(),
                journal=_mock_journal(),
                run_id="RUN-1",
                workspace=WorkspaceId.JAFAR,
                mode=JafarMode.PAPER,  # PAPER n'est pas valide ici
            )

    def test_no_trade_action_blocked(self) -> None:
        from alladin.brain import ProposalParameters

        pid = proposal_identity("RUN-JAFAR-EXEC", "CYC-1", None, "test", "1")
        proposal = ActionProposal(
            proposal_id=pid,
            source_id="test",
            source_version="1",
            run_id="RUN-JAFAR-EXEC",
            cycle_id="CYC-1",
            action=Action.NO_TRADE,
            timestamp=_now(),
            parameters=ProposalParameters(),
        )
        service, _ = self._service()
        result = service.submit(proposal, quantity=0.001)
        assert not result.submitted
        assert result.status is CanonicalOrderStatus.REJECTED

    def test_query_and_reconcile_after_timeout(self) -> None:
        service, adapter = self._service(filled=False)
        proposal = _proposal("LONG")
        result = service.submit(proposal, quantity=0.001)
        assert result.status is CanonicalOrderStatus.PENDING_CONFIRMATION

        # Simuler query exchange qui retourne FILLED
        filled_order = BinanceOrder(
            symbol="BTCUSDT",
            order_id=12345,
            client_order_id=result.client_order_id,
            price=0.0,
            original_quantity=0.001,
            executed_quantity=0.001,
            cumulative_quote_quantity=65.0,
            status="FILLED",
            order_type="MARKET",
            side="BUY",
            created_at=_now(),
            updated_at=_now(),
        )
        adapter.query_order.return_value = filled_order
        status = service.query_and_reconcile("BTCUSDT", result.client_order_id)
        assert status is CanonicalOrderStatus.FILLED


# ---------------------------------------------------------------------------
# JafarRestartReconciler
# ---------------------------------------------------------------------------


class TestJafarRestartReconciler:
    def _reconciler(self, lifecycle=None, read_client=None) -> JafarRestartReconciler:
        lifecycle = lifecycle or _mock_lifecycle()
        read_client = read_client or MagicMock()
        journal = _mock_journal()
        return JafarRestartReconciler(
            lifecycle=lifecycle,
            read_client=read_client,
            journal=journal,
            run_id="RUN-JAFAR-EXEC",
            workspace=WorkspaceId.JAFAR,
            symbols=("BTCUSDT",),
        )

    def test_clean_state_coherent(self) -> None:
        reconciler = self._reconciler()
        # Aucun ordre pending → cohérent
        report = reconciler.reconcile()
        assert report.coherent
        assert report.inspected == 0

    def test_submitting_resolved_to_filled(self) -> None:
        lifecycle = _mock_lifecycle()
        journal = _mock_journal()

        # Créer un claim SUBMITTING en base
        claim = lifecycle.claim("RUN-JAFAR-EXEC", "pid-001", "BTCUSDT", {}, now=_now())
        lifecycle.transition(claim.client_order_id, CanonicalOrderStatus.RISK_APPROVED, now=_now())
        lifecycle.transition(claim.client_order_id, CanonicalOrderStatus.SUBMITTING, now=_now())

        # Exchange retourne FILLED
        filled_order = BinanceOrder(
            symbol="BTCUSDT",
            order_id=12345,
            client_order_id=claim.client_order_id,
            price=0.0,
            original_quantity=0.001,
            executed_quantity=0.001,
            cumulative_quote_quantity=65.0,
            status="FILLED",
            order_type="MARKET",
            side="BUY",
            created_at=_now(),
            updated_at=_now(),
        )
        read_client = MagicMock()
        read_client.query_order.return_value = filled_order
        read_client.open_orders.return_value = ()

        reconciler = JafarRestartReconciler(
            lifecycle=lifecycle,
            read_client=read_client,
            journal=journal,
            run_id="RUN-JAFAR-EXEC",
            workspace=WorkspaceId.JAFAR,
            symbols=("BTCUSDT",),
        )
        report = reconciler.reconcile()
        assert report.resolved == 1
        assert report.coherent

    def test_submitting_absent_exchange_is_ambiguous(self) -> None:
        lifecycle = _mock_lifecycle()
        journal = _mock_journal()

        claim = lifecycle.claim("RUN-JAFAR-EXEC", "pid-002", "BTCUSDT", {}, now=_now())
        lifecycle.transition(claim.client_order_id, CanonicalOrderStatus.RISK_APPROVED, now=_now())
        lifecycle.transition(claim.client_order_id, CanonicalOrderStatus.SUBMITTING, now=_now())

        read_client = MagicMock()
        read_client.query_order.return_value = None  # absent sur exchange
        read_client.open_orders.return_value = ()

        reconciler = JafarRestartReconciler(
            lifecycle=lifecycle,
            read_client=read_client,
            journal=journal,
            run_id="RUN-JAFAR-EXEC",
            workspace=WorkspaceId.JAFAR,
            symbols=("BTCUSDT",),
        )
        report = reconciler.reconcile()
        assert not report.coherent
        assert len(report.ambiguous) == 1

    def test_open_order_on_exchange_not_in_local_is_error(self) -> None:
        lifecycle = _mock_lifecycle()
        journal = _mock_journal()

        # Exchange a un ordre jfr- ouvert qui n'est pas en local
        unknown_order = BinanceOrder(
            symbol="BTCUSDT",
            order_id=99999,
            client_order_id="jfr-unknown-order",
            price=65_000.0,
            original_quantity=0.001,
            executed_quantity=0.0,
            cumulative_quote_quantity=0.0,
            status="NEW",
            order_type="LIMIT",
            side="BUY",
            created_at=_now(),
            updated_at=_now(),
        )
        read_client = MagicMock()
        read_client.open_orders.return_value = (unknown_order,)

        reconciler = JafarRestartReconciler(
            lifecycle=lifecycle,
            read_client=read_client,
            journal=journal,
            run_id="RUN-JAFAR-EXEC",
            workspace=WorkspaceId.JAFAR,
            symbols=("BTCUSDT",),
        )
        report = reconciler.reconcile()
        assert not report.coherent
        assert any("on_exchange_not_in_local" in e.lower() for e in report.errors)
