from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from alladin.api.app import create_app
from alladin.brokers.crypto import CryptoMockProvider
from alladin.brokers.crypto_observe import CryptoObserveBroker
from alladin.core.enums import AssetCategory, JafarMode, MarketRegime, Side
from alladin.core.workspace import WorkspaceId
from alladin.jafar.paper import JafarPaperEngine, JafarPaperRuntime
from alladin.market.models import ScanCandidate, ScanReport
from alladin.orchestration.bootstrap import Components, build_services
from alladin.orchestration.health import RuntimeHealthTracker, RuntimeStatus, StaleMarketDataError
from alladin.orchestration.jafar import JafarModeStore, JafarPaperBrain

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def report(broker: CryptoObserveBroker, *, observed_at: datetime | None, candidate: bool) -> ScanReport:
    tick = broker.tick("BTCUSDT")
    spec = broker.symbol_spec("BTCUSDT")
    assert tick is not None and spec is not None
    candidates = []
    if candidate:
        candidates.append(ScanCandidate(
            symbol="BTCUSDT", category=AssetCategory.CRYPTO_SPOT,
            regime=MarketRegime.TREND, regime_confidence=0.8, score=0.9,
            bias=Side.BUY, metrics={"atr": 1_000.0}, tick=tick, spec=spec,
        ))
    return ScanReport(scanned_at=broker.now(), universe_size=1, analysed=1,
                      candidates=candidates, last_market_update_at=observed_at)


def runtime(settings, reports: list[ScanReport], *, max_failures: int = 3,
            run_id: str | None = None) -> tuple[JafarPaperRuntime, JafarPaperEngine, Components]:
    provider = CryptoMockProvider(start=NOW)
    broker = CryptoObserveBroker(provider)
    comps = build_services(settings, broker, create_run=run_id is None,
                           run_id=run_id, workspace=WorkspaceId.JAFAR)
    assert comps is not None and comps.order_lifecycle is not None
    if comps.jafar_mode is JafarMode.OBSERVE:
        JafarModeStore(comps.journal, comps.run.run_id).transition(JafarMode.PAPER, reason="test")
    if comps.run.watchdog.run_state.value in ("CREATED", "READY"):
        comps.manager.start(comps.run, broker.account_info())
    scanner = MagicMock()
    scanner.scan.side_effect = reports
    engine = JafarPaperEngine(provider=provider, run_id=comps.run.run_id,
                              workspace=WorkspaceId.JAFAR, initial_capital=100_000,
                              repo=comps.repo, lifecycle=comps.order_lifecycle,
                              journal=comps.journal)
    engine.restore()
    health = RuntimeHealthTracker(
        comps.journal, comps.run.run_id, WorkspaceId.JAFAR, "PAPER",
        stale_after_s=60, max_failures=max_failures, backoff_base_s=1,
        backoff_cap_s=2, clock=provider.now,
    )
    return JafarPaperRuntime(
        broker=broker, scanner=scanner, brain=JafarPaperBrain(), risk=comps.risk,
        engine=engine, journal=comps.journal, outcomes=comps.outcomes,
        run_state=lambda: comps.run.watchdog.run_state, health=health,
    ), engine, comps


def test_stale_data_blocks_new_entry(settings) -> None:
    provider = CryptoMockProvider(start=NOW)
    broker = CryptoObserveBroker(provider)
    stale = report(broker, observed_at=NOW - timedelta(seconds=61), candidate=True)
    service, engine, _ = runtime(settings, [stale])
    with pytest.raises(StaleMarketDataError):
        service.run_cycle()
    assert service.health.health.status is RuntimeStatus.STALE
    assert engine.open_positions() == []


def test_provider_error_backoff_recovery_and_counter_reset(settings) -> None:
    provider = CryptoMockProvider(start=NOW)
    broker = CryptoObserveBroker(provider)
    down = report(broker, observed_at=None, candidate=False)
    fresh = report(broker, observed_at=NOW, candidate=False)
    service, _, comps = runtime(settings, [down, down, fresh])
    sleeps: list[float] = []
    service.run_loop(0, max_cycles=3, sleep=sleeps.append, handle_signals=False)
    events = comps.repo.events(comps.run.run_id, ["runtime.health"])
    assert sleeps == [1.0, 2.0]
    assert any(e.payload["status"] == "HEALTHY" and e.payload["consecutive_failures"] == 0
               for e in events)
    assert service.health.health.status is RuntimeStatus.STOPPED


def test_failure_threshold_is_fail_closed_and_preserves_positions(settings) -> None:
    provider = CryptoMockProvider(start=NOW)
    broker = CryptoObserveBroker(provider)
    fresh = report(broker, observed_at=NOW, candidate=True)
    down = report(broker, observed_at=None, candidate=False)
    service, engine, _ = runtime(settings, [fresh, down, down], max_failures=2)
    service.run_cycle()
    assert len(engine.open_positions()) == 1
    sleeps: list[float] = []
    service.run_loop(0, max_cycles=2, sleep=sleeps.append, handle_signals=False)
    assert service.health.health.status is RuntimeStatus.FAILED
    assert len(engine.open_positions()) == 1
    assert sleeps == [1.0]


def test_graceful_shutdown_transitions_and_never_writes_broker(settings) -> None:
    provider = CryptoMockProvider(start=NOW)
    broker = CryptoObserveBroker(provider)
    fresh = report(broker, observed_at=NOW, candidate=False)
    service, _, comps = runtime(settings, [fresh])
    broker._send = MagicMock(side_effect=AssertionError("write interdit"))  # type: ignore[method-assign]
    service.run_loop(0, max_cycles=10, on_cycle=lambda _: service.request_stop("test stop"),
                     sleep=lambda _: None, handle_signals=False)
    statuses = [e.payload["status"] for e in comps.repo.events(comps.run.run_id, ["runtime.health"])]
    assert statuses[-2:] == ["STOPPING", "STOPPED"]
    broker._send.assert_not_called()


def test_restart_restores_position_and_prevents_duplicate_symbol(settings) -> None:
    provider = CryptoMockProvider(start=NOW)
    broker = CryptoObserveBroker(provider)
    fresh = report(broker, observed_at=NOW, candidate=True)
    first, engine, comps = runtime(settings, [fresh])
    assert first.run_cycle().decision == "TRADE"
    position_id = engine.open_positions()[0].position_id

    restarted, restored, _ = runtime(settings, [fresh], run_id=comps.run.run_id)
    result = restarted.run_cycle()
    assert result.decision == "NO_TRADE"
    assert [p.position_id for p in restored.open_positions()] == [position_id]


def test_runtime_health_api_is_read_only_and_reports_persisted_state(settings) -> None:
    provider = CryptoMockProvider(start=NOW)
    broker = CryptoObserveBroker(provider)
    fresh = report(broker, observed_at=NOW, candidate=False)
    service, _, comps = runtime(settings, [fresh])
    service.run_cycle()
    api_settings = comps.settings.model_copy(update={"runtime_stale_after_s": 1_000_000_000.0})
    api = TestClient(create_app(api_settings, comps.repo, comps.broker))
    response = api.get("/api/runtime/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"] == comps.run.run_id
    assert payload["status"] == "HEALTHY"
    assert payload["provider_status"] == "UP"
    assert api.post("/api/runtime/health").status_code == 405
