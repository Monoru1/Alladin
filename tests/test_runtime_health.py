from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from alladin.core.workspace import WorkspaceId
from alladin.journal.models import RunRecord
from alladin.journal.repository import JournalRepository
from alladin.journal.service import JournalService
from alladin.orchestration.health import (
    ProviderStatus,
    RuntimeHealthTracker,
    RuntimeStatus,
    StaleMarketDataError,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def tracker(clock: FakeClock, *, journal: JournalService | None = None) -> RuntimeHealthTracker:
    journal = journal or JournalService(JournalRepository.from_url("sqlite://", WorkspaceId.JAFAR), clock)
    if journal.repo.get_run("RUN-JAFAR-001") is None:
        journal.repo.create_run(RunRecord(
            run_id="RUN-JAFAR-001", seq=1, profile_id="jafar_observe",
            state="RUNNING", phase=1, initial_balance=100_000,
            broker="CRYPTO_PUBLIC_OBSERVE", account="NO-ACCOUNT@crypto:mock",
            magic=27_000_001, kind="RUN", created_at=clock.now,
            updated_at=clock.now, watchdog_state={}, workspace=WorkspaceId.JAFAR,
        ))
    return RuntimeHealthTracker(
        journal, "RUN-JAFAR-001", WorkspaceId.JAFAR, "PAPER",
        stale_after_s=60, max_failures=3, backoff_base_s=2, backoff_cap_s=5,
        clock=clock,
    )


def test_heartbeat_and_cycle_progress_are_persisted() -> None:
    clock = FakeClock()
    health = tracker(clock)
    clock.advance(5)
    health.heartbeat()
    assert health.health.last_heartbeat_at == clock.now
    clock.advance(5)
    health.cycle_completed()
    restored = RuntimeHealthTracker.load_latest(health.journal, health.run_id)
    assert restored is not None and restored.last_cycle_at == clock.now


def test_fresh_market_is_healthy_and_stale_market_fails_closed() -> None:
    clock = FakeClock()
    health = tracker(clock)
    assert health.market_progress(clock.now).status is RuntimeStatus.HEALTHY
    assert health.health.provider_status is ProviderStatus.UP
    with pytest.raises(StaleMarketDataError):
        health.market_progress(clock.now - timedelta(seconds=61))
    assert health.health.status is RuntimeStatus.STALE
    assert health.health.provider_status is ProviderStatus.STALE


def test_provider_failures_backoff_cap_and_recovery() -> None:
    clock = FakeClock()
    health = tracker(clock)
    assert health.provider_failure("timeout").status is RuntimeStatus.DEGRADED
    assert health.backoff_seconds() == 2
    assert health.provider_failure("timeout").consecutive_failures == 2
    assert health.backoff_seconds() == 4
    assert health.provider_failure("timeout").status is RuntimeStatus.FAILED
    assert health.backoff_seconds() == 5
    recovered = health.market_progress(clock.now)
    assert recovered.status is RuntimeStatus.HEALTHY
    assert recovered.consecutive_failures == 0 and recovered.last_error is None


def test_restart_restores_degraded_state_then_recovers() -> None:
    clock = FakeClock()
    first = tracker(clock)
    first.provider_failure("provider down")
    restarted = tracker(clock, journal=first.journal)
    assert restarted.health.status is RuntimeStatus.DEGRADED
    assert restarted.health.consecutive_failures == 1
    assert restarted.market_progress(clock.now).status is RuntimeStatus.HEALTHY


def test_graceful_state_sequence_is_persisted() -> None:
    clock = FakeClock()
    health = tracker(clock)
    assert health.stopping("SIGTERM").status is RuntimeStatus.STOPPING
    assert health.stopped().status is RuntimeStatus.STOPPED
    assert RuntimeHealthTracker.load_latest(health.journal, health.run_id) == health.health
