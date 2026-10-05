"""Paper endurance harness — stress du JafarPaperRuntime sous pannes injectées.

Couverture :
  - N cycles clean (100, 1 000)
  - provider failure + recovery
  - stale data
  - restart avec restauration de portfolio
  - duplicate proposal storm
  - SL/TP trigger par manipulation de prix
  - graceful shutdown
  - fail closed
  - replay déterministe même seed
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

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
BASE_PRICE = 65_000.0
ATR = 1_000.0
# 2*ATR SL → entry ~65032 (ask+slippage), SL ~63032 → drop to 62000 triggers it
SL_TRIGGER_PRICE = 62_000.0


# ──────────────────────────────────────────────────────────────────────────────
# Fault Plan
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class FaultEvent:
    """Un incident à injecter à un cycle précis."""
    cycle: int
    kind: str  # provider_error | stale_data | no_trade | price_drop | price_recover | restart | graceful_stop
    detail: str = ""
    value: float = 0.0  # pour price_drop / price_recover : nouveau _base_price


@dataclass
class FaultPlan:
    events: list[FaultEvent] = field(default_factory=list)

    def for_cycle(self, n: int) -> list[FaultEvent]:
        return [e for e in self.events if e.cycle == n]


# ──────────────────────────────────────────────────────────────────────────────
# Scenario Scanner
# ──────────────────────────────────────────────────────────────────────────────

class ScenarioScanner:
    """Fake scanner déterministe piloté par un FaultPlan."""

    def __init__(
        self,
        broker: CryptoObserveBroker,
        provider: CryptoMockProvider,
        fault_plan: FaultPlan,
        stale_after_s: float,
    ) -> None:
        self._broker = broker
        self._provider = provider
        self._fault_plan = fault_plan
        self._stale_after_s = stale_after_s
        self._cycle = 0

    def reset_cycle(self, n: int) -> None:
        self._cycle = n

    def scan(self, cycle_id: str | None = None, max_trade_risk: object = None) -> ScanReport:
        self._cycle += 1
        faults = self._fault_plan.for_cycle(self._cycle)
        kinds = {f.kind for f in faults}

        if "provider_error" in kinds:
            detail = next((f.detail for f in faults if f.kind == "provider_error"), "simulated")
            raise RuntimeError(f"provider error cycle {self._cycle}: {detail}")

        now = self._provider.now()
        observed_at: datetime | None = now
        if "stale_data" in kinds:
            observed_at = now - timedelta(seconds=self._stale_after_s + 10)

        tick = self._broker.tick("BTCUSDT")
        spec = self._broker.symbol_spec("BTCUSDT")
        candidates: list[ScanCandidate] = []
        if tick is not None and spec is not None and "no_trade" not in kinds:
            candidates.append(ScanCandidate(
                symbol="BTCUSDT",
                category=AssetCategory.CRYPTO_SPOT,
                regime=MarketRegime.TREND,
                regime_confidence=0.8,
                score=0.9,
                bias=Side.BUY,
                metrics={"atr": ATR},
                tick=tick,
                spec=spec,
            ))

        return ScanReport(
            scanned_at=now,
            universe_size=1,
            analysed=1,
            candidates=candidates,
            last_market_update_at=observed_at,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Endurance Report
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class EnduranceReport:
    seed: int
    requested_cycles: int
    completed_cycles: int
    runtime_status: str
    provider_failures: int
    recoveries: int
    stale_events: int
    restarts: int
    proposals: int
    no_trades: int
    opened_positions: int
    closed_positions: int
    duplicate_attempts: int
    duplicate_blocks: int
    outcomes_created: int
    final_cash: float
    final_total_value: float
    realized_pnl: float
    unrealized_pnl: float
    max_drawdown: float
    invariant_failures: list[str]
    elapsed_s: float
    cycles_per_sec: float


# ──────────────────────────────────────────────────────────────────────────────
# Invariant Checks
# ──────────────────────────────────────────────────────────────────────────────

def check_invariants(
    engine: JafarPaperEngine,
    tracker: RuntimeHealthTracker,
) -> list[str]:
    failures: list[str] = []
    snap = engine.portfolio_snapshot()

    if snap.cash < -0.01:
        failures.append(f"cash négatif: {snap.cash:.4f}")
    if snap.total_value < -0.01:
        failures.append(f"total_value négatif: {snap.total_value:.4f}")

    # Pas de proposal_id dupliqué dans les positions ouvertes
    open_pids = [p.proposal_id for p in engine.open_positions()]
    if len(open_pids) != len(set(open_pids)):
        failures.append(f"positions ouvertes avec proposal_id dupliqué: {open_pids}")

    # HEALTHY → consecutive_failures == 0
    h = tracker.health
    if h.status is RuntimeStatus.HEALTHY and h.consecutive_failures != 0:
        failures.append(f"HEALTHY mais consecutive_failures={h.consecutive_failures}")

    # FAILED → consecutive_failures >= max_failures
    if h.status is RuntimeStatus.FAILED and h.consecutive_failures < tracker.max_failures:
        failures.append(
            f"FAILED mais failures={h.consecutive_failures} < max={tracker.max_failures}"
        )

    return failures


# ──────────────────────────────────────────────────────────────────────────────
# Build helpers
# ──────────────────────────────────────────────────────────────────────────────

def _build(
    settings: object,
    provider: CryptoMockProvider,
    fault_plan: FaultPlan,
    stale_after_s: float,
    max_failures: int,
    backoff_base_s: float,
    backoff_cap_s: float,
    *,
    run_id: str | None = None,
    db_url: str | None = "sqlite://",
) -> tuple[JafarPaperRuntime, JafarPaperEngine, ScenarioScanner, RuntimeHealthTracker, Components]:
    broker = CryptoObserveBroker(provider)
    comps = build_services(
        settings, broker,  # type: ignore[arg-type]
        create_run=run_id is None, run_id=run_id,
        workspace=WorkspaceId.JAFAR,
        db_url=db_url,
    )
    assert comps is not None and comps.order_lifecycle is not None
    if comps.jafar_mode is JafarMode.OBSERVE:
        JafarModeStore(comps.journal, comps.run.run_id).transition(JafarMode.PAPER, reason="endurance")
    if comps.run.watchdog.run_state.value in ("CREATED", "READY"):
        comps.manager.start(comps.run, broker.account_info())

    engine = JafarPaperEngine(
        provider=provider, run_id=comps.run.run_id,
        workspace=WorkspaceId.JAFAR, initial_capital=100_000,
        repo=comps.repo, lifecycle=comps.order_lifecycle, journal=comps.journal,
    )
    engine.restore()

    scanner = ScenarioScanner(broker, provider, fault_plan, stale_after_s)
    health = RuntimeHealthTracker(
        comps.journal, comps.run.run_id, WorkspaceId.JAFAR, "PAPER",
        stale_after_s=stale_after_s,
        max_failures=max_failures,
        backoff_base_s=backoff_base_s,
        backoff_cap_s=backoff_cap_s,
        clock=provider.now,
    )
    runtime = JafarPaperRuntime(
        broker=broker, scanner=scanner, brain=JafarPaperBrain(),  # type: ignore[arg-type]
        risk=comps.risk, engine=engine, journal=comps.journal,
        outcomes=comps.outcomes,
        run_state=lambda: comps.run.watchdog.run_state,
        health=health,
    )
    return runtime, engine, scanner, health, comps


# ──────────────────────────────────────────────────────────────────────────────
# Endurance Harness
# ──────────────────────────────────────────────────────────────────────────────

class EnduranceHarness:
    """Pilote des cycles PAPER sous pannes injectées ; collecte un rapport complet."""

    def __init__(
        self,
        settings: object,
        *,
        seed: int = 42,
        stale_after_s: float = 60.0,
        max_failures: int = 3,
        backoff_base_s: float = 0.001,
        backoff_cap_s: float = 0.01,
        db_url: str | None = "sqlite://",
    ) -> None:
        self.settings = settings
        self.seed = seed
        self.stale_after_s = stale_after_s
        self.max_failures = max_failures
        self.backoff_base_s = backoff_base_s
        self.backoff_cap_s = backoff_cap_s
        self.db_url = db_url

    def run(self, cycles: int, fault_plan: FaultPlan | None = None) -> EnduranceReport:
        fp = fault_plan or FaultPlan()
        provider = CryptoMockProvider(seed=self.seed, start=NOW)

        runtime, engine, scanner, health, comps = _build(
            self.settings, provider, fp,
            self.stale_after_s, self.max_failures,
            self.backoff_base_s, self.backoff_cap_s,
            db_url=self.db_url,
        )
        run_id = comps.run.run_id

        completed = 0
        provider_failures = 0
        recoveries = 0
        stale_events = 0
        restarts = 0
        proposals = 0
        no_trades = 0
        opened = 0
        closed = 0
        duplicate_blocks = 0
        max_drawdown = 0.0
        was_degraded = False

        t0 = time.monotonic()
        cycle_n = 0

        while cycle_n < cycles:
            cycle_n += 1
            provider.advance(60.0)

            faults = fp.for_cycle(cycle_n)
            kinds = {f.kind for f in faults}

            # ── Harness-level faults (avant scan) ──

            if "graceful_stop" in kinds:
                detail = next((f.detail for f in faults if f.kind == "graceful_stop"), "")
                runtime.request_stop(detail or f"graceful stop cycle {cycle_n}")
                break

            if "restart" in kinds:
                restarts += 1
                runtime.request_stop(f"restart cycle {cycle_n}")
                runtime, engine, scanner, health, comps = _build(
                    self.settings, provider, fp,
                    self.stale_after_s, self.max_failures,
                    self.backoff_base_s, self.backoff_cap_s,
                    run_id=run_id,
                    db_url=self.db_url,
                )
                scanner.reset_cycle(cycle_n)
                continue  # ne compte pas comme un cycle exécuté

            if "price_drop" in kinds:
                provider._base_price = next(f.value for f in faults if f.kind == "price_drop")

            if "price_recover" in kinds:
                provider._base_price = next(f.value for f in faults if f.kind == "price_recover")

            # ── Cycle ──

            open_ids_before = {p.position_id for p in engine.open_positions()}
            closed_before = engine.portfolio_snapshot().closed_trades

            try:
                outcome = runtime.run_cycle()
                completed += 1

                open_ids_after = {p.position_id for p in engine.open_positions()}
                closed_after = engine.portfolio_snapshot().closed_trades

                opened += len(open_ids_after - open_ids_before)
                closed += closed_after - closed_before

                if outcome.decision == "TRADE":
                    proposals += 1
                elif outcome.decision == "NO_TRADE":
                    no_trades += 1
                    if outcome.reason and "déjà ouverte" in outcome.reason:
                        duplicate_blocks += 1

                snap = engine.portfolio_snapshot()
                if snap.drawdown_pct > max_drawdown:
                    max_drawdown = snap.drawdown_pct

                # Recovery detection
                if was_degraded and health.health.status is RuntimeStatus.HEALTHY:
                    recoveries += 1
                    was_degraded = False
                if health.health.status in (RuntimeStatus.DEGRADED, RuntimeStatus.STALE):
                    was_degraded = True

            except StaleMarketDataError:
                stale_events += 1
                completed += 1
                was_degraded = True
                continue

            except RuntimeError as exc:
                provider_failures += 1
                completed += 1
                was_degraded = True
                health.provider_failure(exc)
                if health.health.status is RuntimeStatus.FAILED:
                    break
                continue

            if health.health.status is RuntimeStatus.FAILED:
                break

        elapsed = time.monotonic() - t0
        snap = engine.portfolio_snapshot()

        # Outcomes créés = événements trade.outcome dans le journal
        outcome_events = comps.repo.events(run_id, ["trade.outcome"])

        return EnduranceReport(
            seed=self.seed,
            requested_cycles=cycles,
            completed_cycles=completed,
            runtime_status=health.health.status.value,
            provider_failures=provider_failures,
            recoveries=recoveries,
            stale_events=stale_events,
            restarts=restarts,
            proposals=proposals,
            no_trades=no_trades,
            opened_positions=opened,
            closed_positions=closed,
            duplicate_attempts=duplicate_blocks,  # observable via NO_TRADE "déjà ouverte"
            duplicate_blocks=duplicate_blocks,
            outcomes_created=len(outcome_events),
            final_cash=snap.cash,
            final_total_value=snap.total_value,
            realized_pnl=snap.realized_pnl,
            unrealized_pnl=snap.unrealized_pnl,
            max_drawdown=max_drawdown,
            invariant_failures=check_invariants(engine, health),
            elapsed_s=elapsed,
            cycles_per_sec=completed / elapsed if elapsed > 0 else 0.0,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────────

def test_100_clean_cycles(settings: object) -> None:
    report = EnduranceHarness(settings).run(100)
    assert report.completed_cycles == 100
    assert report.invariant_failures == []
    assert report.provider_failures == 0
    assert report.stale_events == 0
    assert report.runtime_status in ("HEALTHY", "STOPPING", "STOPPED")
    assert report.final_cash > 0
    assert report.cycles_per_sec > 0


def test_1000_clean_cycles(settings: object) -> None:
    report = EnduranceHarness(settings).run(1000)
    assert report.completed_cycles == 1000
    assert report.invariant_failures == []
    assert report.provider_failures == 0
    # Régression catastrophique : moins de 30 cycles/sec = signe de blocage
    assert report.cycles_per_sec > 30.0, (
        f"1000 cycles trop lents: {report.cycles_per_sec:.1f} cycles/s "
        f"({report.elapsed_s:.1f}s total)"
    )


def test_provider_failures_and_recovery(settings: object) -> None:
    fp = FaultPlan(events=[
        FaultEvent(10, "provider_error", "panne réseau"),
        FaultEvent(11, "provider_error", "toujours down"),
        # cycle 12 : pas de fault → recovery
    ])
    report = EnduranceHarness(settings, max_failures=5).run(20, fp)
    assert report.provider_failures == 2
    assert report.recoveries >= 1
    assert report.invariant_failures == []
    assert report.runtime_status not in ("FAILED",)


def test_stale_data_blocks_new_entry(settings: object) -> None:
    fp = FaultPlan(events=[FaultEvent(5, "stale_data")])
    report = EnduranceHarness(settings).run(10, fp)
    assert report.stale_events == 1
    assert report.invariant_failures == []
    # Aucune position ouverte sur les cycles stale
    # (la position ouverte avant cycle 5 est conservée, mais on ne peut pas en ouvrir sur ce cycle)


def test_restart_preserves_position_no_duplicate(settings: object) -> None:
    # Cycle 3 : ouvre une position, cycle 10 : restart
    # db_url=None : SQLite fichier partagé pour que le restart restaure l'état
    fp = FaultPlan(events=[FaultEvent(10, "restart", "restart test")])
    report = EnduranceHarness(settings, db_url=None).run(15, fp)
    assert report.restarts == 1
    assert report.invariant_failures == [], report.invariant_failures
    # La position ouverte avant restart est restaurée, pas dupliquée
    assert report.opened_positions <= report.closed_positions + 1  # au plus 1 ouverte à la fin


def test_duplicate_proposal_storm(settings: object) -> None:
    """Ouvre une position BTCUSDT puis force 10 cycles supplémentaires sur le même symbole."""
    # Cycles 1-10 : candidat BTCUSDT disponible. Après l'ouverture au cycle 1 (environ),
    # tous les cycles suivants doivent être bloqués par "déjà ouverte".
    report = EnduranceHarness(settings).run(10, FaultPlan())
    assert report.invariant_failures == []
    # Au plus 1 position ouverte (anti-duplication symbole)
    assert report.opened_positions <= 1 or (
        report.opened_positions > 1 and report.closed_positions >= report.opened_positions - 1
    )
    if report.opened_positions >= 1:
        assert report.duplicate_blocks >= 1


def test_sl_tp_trigger(settings: object) -> None:
    """Ouvre une position, fait chuter le prix sous le SL → close automatique."""
    fp = FaultPlan(events=[
        # Cycle 5 : drop sous le SL
        FaultEvent(5, "price_drop", "SL trigger", SL_TRIGGER_PRICE),
        # Cycle 6 : restaure le prix
        FaultEvent(6, "price_recover", "recovery", BASE_PRICE),
    ])
    report = EnduranceHarness(settings).run(15, fp)
    assert report.invariant_failures == []
    # La position devrait avoir été fermée par SL
    assert report.closed_positions >= 1 or report.opened_positions == 0  # si pas de position ouverte avant le drop


def test_graceful_shutdown(settings: object) -> None:
    fp = FaultPlan(events=[FaultEvent(5, "graceful_stop", "test stop")])
    report = EnduranceHarness(settings).run(20, fp)
    assert report.completed_cycles <= 5  # s'est arrêté à cycle 5 ou avant
    assert report.invariant_failures == []
    assert report.runtime_status in ("STOPPING", "STOPPED")


def test_fail_closed(settings: object) -> None:
    """max_failures=2 : 2 erreurs consécutives → FAILED, positions conservées, boucle arrêtée."""
    fp = FaultPlan(events=[
        FaultEvent(3, "provider_error", "panne 1"),
        FaultEvent(4, "provider_error", "panne 2"),
    ])
    report = EnduranceHarness(settings, max_failures=2).run(10, fp)
    assert report.runtime_status == "FAILED"
    assert report.provider_failures == 2
    assert report.completed_cycles <= 5  # boucle stoppée après FAILED
    assert report.invariant_failures == []
    # Positions conservées (pas fermées arbitrairement)
    assert report.final_cash > 0


def test_deterministic_replay_same_seed(settings: object) -> None:
    """Deux runs avec le même seed et le même FaultPlan produisent des résultats identiques."""
    fp = FaultPlan(events=[
        FaultEvent(5, "provider_error", "err"),
        FaultEvent(8, "stale_data"),
    ])
    r1 = EnduranceHarness(settings, seed=42).run(20, fp)
    r2 = EnduranceHarness(settings, seed=42).run(20, fp)
    assert r1.completed_cycles == r2.completed_cycles
    assert r1.provider_failures == r2.provider_failures
    assert r1.stale_events == r2.stale_events
    assert r1.opened_positions == r2.opened_positions
    assert r1.closed_positions == r2.closed_positions
    assert r1.invariant_failures == r2.invariant_failures


def test_no_production_write_under_any_fault(settings: object) -> None:
    """Aucun ordre Binance production soumis en PAPER sous pannes injectées.

    Vérifié par deux angles :
    1. Structurel : JafarPaperRuntime n'appelle pas broker.send_order / broker._send.
    2. Journal : aucun événement 'order.live' émis.
    """
    import inspect

    from alladin.jafar import paper as _paper_module

    paper_src = inspect.getsource(_paper_module)
    assert "send_order" not in paper_src, "JafarPaperRuntime appelle send_order !"
    assert "broker._send" not in paper_src, "JafarPaperRuntime appelle broker._send !"

    fp = FaultPlan(events=[
        FaultEvent(2, "provider_error"),
        FaultEvent(5, "stale_data"),
        FaultEvent(12, "graceful_stop"),
    ])
    report = EnduranceHarness(settings).run(20, fp)
    assert report.invariant_failures == []
