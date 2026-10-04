from datetime import UTC, datetime

import pytest

from alladin.brokers.binance import BinanceOrder
from alladin.core.workspace import WorkspaceId
from alladin.execution.order_lifecycle import (
    CanonicalOrderStatus,
    JafarStartupReconciler,
    OrderLifecycleError,
    OrderLifecycleRepository,
)
from alladin.journal.repository import make_engine

T0 = datetime(2026, 10, 4, 12, tzinfo=UTC)


def exchange(
    client_order_id: str, status: str, *, symbol: str = "BTCUSDT", executed: float = 0.0
) -> BinanceOrder:
    return BinanceOrder(
        symbol=symbol,
        order_id=42,
        client_order_id=client_order_id,
        price=65000,
        original_quantity=0.01,
        executed_quantity=executed,
        cumulative_quote_quantity=executed * 65000,
        status=status,
        order_type="LIMIT",
        side="BUY",
        created_at=T0,
        updated_at=T0,
    )


def repository():
    return OrderLifecycleRepository(make_engine("sqlite://"), WorkspaceId.JAFAR)


def approved(repo: OrderLifecycleRepository):
    claim = repo.claim("RUN-JAFAR-1", "proposal-1", "BTCUSDT", {"quantity": "0.01"}, now=T0)
    return repo.transition(claim.client_order_id, CanonicalOrderStatus.RISK_APPROVED, now=T0)


def test_claim_is_deterministic_idempotent_and_rejects_payload_reuse():
    repo = repository()
    first = repo.claim("RUN-JAFAR-1", "proposal-1", "BTCUSDT", {"quantity": "0.01"}, now=T0)
    same = repo.claim("RUN-JAFAR-1", "proposal-1", "BTCUSDT", {"quantity": "0.01"}, now=T0)
    assert same == first and first.client_order_id.startswith("jfr-")
    assert len(first.client_order_id) <= 36
    with pytest.raises(OrderLifecycleError, match="contenu different"):
        repo.claim("RUN-JAFAR-1", "proposal-1", "BTCUSDT", {"quantity": "0.02"}, now=T0)


def test_risk_rejection_is_terminal_and_cannot_submit():
    repo = repository()
    claim = repo.claim("run", "proposal", "BTCUSDT", {}, now=T0)
    rejected = repo.transition(claim.client_order_id, CanonicalOrderStatus.REJECTED, now=T0)
    assert rejected.status.terminal
    with pytest.raises(OrderLifecycleError, match="transition interdite"):
        repo.transition(claim.client_order_id, CanonicalOrderStatus.SUBMITTING, now=T0)


def test_timeout_becomes_pending_and_restart_never_resubmits(tmp_path):
    url = f"sqlite:///{(tmp_path / 'orders.db').as_posix()}"
    repo = OrderLifecycleRepository(make_engine(url), WorkspaceId.JAFAR)
    claim = approved(repo)
    submitting = repo.transition(claim.client_order_id, CanonicalOrderStatus.SUBMITTING, now=T0)
    pending = repo.reconcile(submitting.client_order_id, None)
    assert pending.status is CanonicalOrderStatus.PENDING_CONFIRMATION

    restarted = OrderLifecycleRepository(make_engine(url), WorkspaceId.JAFAR)
    assert restarted.pending_reconciliation()[0].client_order_id == pending.client_order_id
    with pytest.raises(OrderLifecycleError):
        restarted.transition(pending.client_order_id, CanonicalOrderStatus.SUBMITTING, now=T0)
    assert (
        restarted.reconcile(pending.client_order_id, None).status is CanonicalOrderStatus.PENDING_CONFIRMATION
    )


def test_reconciliation_tracks_partial_fill_then_fill_without_duplicate_claim():
    repo = repository()
    claim = approved(repo)
    repo.transition(claim.client_order_id, CanonicalOrderStatus.SUBMITTING, now=T0)
    partial = repo.reconcile(
        claim.client_order_id, exchange(claim.client_order_id, "PARTIALLY_FILLED", executed=0.005)
    )
    assert partial.status is CanonicalOrderStatus.PARTIALLY_FILLED and partial.exchange_order_id == 42
    filled = repo.reconcile(claim.client_order_id, exchange(claim.client_order_id, "FILLED", executed=0.01))
    assert filled.status is CanonicalOrderStatus.FILLED and filled.status.terminal
    with pytest.raises(OrderLifecycleError, match="non reconciliable"):
        repo.reconcile(claim.client_order_id, exchange(claim.client_order_id, "FILLED", executed=0.01))


def test_exchange_identity_divergence_fails_closed():
    repo = repository()
    claim = approved(repo)
    repo.transition(claim.client_order_id, CanonicalOrderStatus.SUBMITTING, now=T0)
    with pytest.raises(OrderLifecycleError, match="fail closed"):
        repo.reconcile(claim.client_order_id, exchange("other-client-id", "NEW"))
    assert repo.get(claim.client_order_id).status is CanonicalOrderStatus.SUBMITTING  # type: ignore[union-attr]


def test_workspace_order_claims_are_isolated():
    engine = make_engine("sqlite://")
    jafar = OrderLifecycleRepository(engine, WorkspaceId.JAFAR)
    alladin = OrderLifecycleRepository(engine, WorkspaceId.ALLADIN)
    claim = jafar.claim("same-run", "same-proposal", "BTCUSDT", {}, now=T0)
    assert jafar.get(claim.client_order_id) is not None
    assert alladin.get(claim.client_order_id) is None


def test_startup_reconciles_lost_ack_without_resubmission():
    repo = repository()
    claim = approved(repo)
    repo.transition(claim.client_order_id, CanonicalOrderStatus.SUBMITTING, now=T0)
    calls = []

    def lookup(symbol, client_order_id):
        calls.append((symbol, client_order_id))
        return exchange(client_order_id, "NEW")

    report = JafarStartupReconciler(repo, lookup).reconcile()
    assert report.coherent and report.resolved == 1
    assert repo.get(claim.client_order_id).status is CanonicalOrderStatus.ACKNOWLEDGED  # type: ignore[union-attr]
    assert calls == [("BTCUSDT", claim.client_order_id)]


def test_startup_absent_order_stays_ambiguous_across_restarts():
    repo = repository()
    claim = approved(repo)
    repo.transition(claim.client_order_id, CanonicalOrderStatus.SUBMITTING, now=T0)
    first = JafarStartupReconciler(repo, lambda _symbol, _client_id: None).reconcile()
    second = JafarStartupReconciler(repo, lambda _symbol, _client_id: None).reconcile()
    assert not first.coherent and not second.coherent
    assert repo.get(claim.client_order_id).status is CanonicalOrderStatus.PENDING_CONFIRMATION  # type: ignore[union-attr]


def test_startup_partial_fill_and_lookup_error_fail_closed():
    repo = repository()
    claim = approved(repo)
    repo.transition(claim.client_order_id, CanonicalOrderStatus.SUBMITTING, now=T0)
    partial = JafarStartupReconciler(
        repo,
        lambda _symbol, client_id: exchange(client_id, "PARTIALLY_FILLED", executed=0.005),
    ).reconcile()
    assert partial.coherent and partial.resolved == 1
    assert repo.get(claim.client_order_id).status is CanonicalOrderStatus.PARTIALLY_FILLED  # type: ignore[union-attr]

    def unavailable(_symbol, _client_id):
        raise TimeoutError

    failed = JafarStartupReconciler(repo, unavailable).reconcile()
    assert not failed.coherent and failed.errors
