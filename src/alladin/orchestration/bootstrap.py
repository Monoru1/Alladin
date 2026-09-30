"""Assemblage des composants (utilisé par la CLI, la démo et les tests d'intégration)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from alladin.agents.base import AgentAdapter
from alladin.agents.claude import ClaudeAdapter
from alladin.agents.codex import CodexAdapter
from alladin.agents.mock import MockAgent
from alladin.brokers.base import BrokerAdapter
from alladin.brokers.mock import MockBroker
from alladin.brokers.mt5 import MT5Broker
from alladin.challenge.models import ChallengeProfile
from alladin.challenge.profiles import load_profile
from alladin.core.config import Settings
from alladin.core.errors import AlladinError
from alladin.core.killswitch import KillSwitch
from alladin.execution.service import ExecutionService
from alladin.journal.repository import JournalRepository
from alladin.journal.service import JournalService
from alladin.market.scanner import MarketScanner
from alladin.market.universe import MarketUniverse
from alladin.orchestration.engine import OrchestrationEngine
from alladin.orchestration.monitor import PositionMonitor
from alladin.orchestration.state import RunContext, RunManager
from alladin.risk.engine import RiskEngine
from alladin.strategies.registry import StrategyRegistry
from alladin.strategies.router import StrategyRouter


def make_broker(kind: str, settings: Settings, profile: ChallengeProfile | None = None) -> BrokerAdapter:
    if kind == "mock":
        return MockBroker(balance=profile.initial_balance if profile else 100_000.0)
    if kind == "mt5":
        return MT5Broker(
            path=settings.mt5_path,
            login=settings.mt5_login,
            password=settings.mt5_password,
            server=settings.mt5_server,
            timeout_ms=settings.mt5_timeout_ms,
            server_utc_offset_hours=settings.mt5_server_utc_offset_hours,
        )
    raise AlladinError(f"broker inconnu : {kind}")


def make_agent(kind: str, settings: Settings) -> AgentAdapter:
    if kind == "mock":
        return MockAgent()
    if kind == "claude":
        return ClaudeAdapter(timeout_s=settings.agent_timeout_s)
    if kind == "codex":
        return CodexAdapter(timeout_s=settings.agent_timeout_s)
    raise AlladinError(f"agent inconnu : {kind}")


@dataclass
class Components:
    settings: Settings
    profile: ChallengeProfile
    broker: BrokerAdapter
    repo: JournalRepository
    journal: JournalService
    manager: RunManager
    killswitch: KillSwitch
    run: RunContext
    risk: RiskEngine
    execution: ExecutionService
    monitor: PositionMonitor

    def engine(self, agent: AgentAdapter, *, execute: bool) -> OrchestrationEngine:
        registry = StrategyRegistry.from_config(self.settings.strategies_dir)
        universe = MarketUniverse(self.broker, self.profile.universe)
        scanner = MarketScanner(self.broker, universe, self.profile.universe)
        router = StrategyRouter(registry, performance=self.journal)
        return OrchestrationEngine(
            broker=self.broker,
            run=self.run,
            manager=self.manager,
            journal=self.journal,
            scanner=scanner,
            router=router,
            agent=agent,
            execution=self.execution,
            monitor=self.monitor,
            execute=execute,
        )


def build_services(
    settings: Settings,
    broker: BrokerAdapter,
    *,
    profile_id: str | None = None,
    run_id: str | None = None,
    create_run: bool = False,
    db_url: str | None = None,
    clock: Callable[[], datetime] | None = None,
    killswitch_path: Path | None = None,
) -> Components | None:
    """Retourne None si aucun run n'existe et que `create_run` est faux."""
    repo = JournalRepository.from_url(db_url or settings.db_url)
    clk = clock or broker.now
    journal = JournalService(repo, clk)
    killswitch = KillSwitch(killswitch_path or settings.kill_switch_path)
    manager = RunManager(repo, journal, killswitch, settings.magic_base, clk)

    existing = run_id or manager.latest_run_id(only_open=True)
    if existing and not create_run:
        rec = repo.get_run(existing)
        if rec is None:
            raise AlladinError(f"run introuvable : {existing}")
        profile = load_profile(rec.profile_id, settings.profiles_dir)
        run = manager.load_run(existing, profile)
    elif create_run:
        profile = load_profile(profile_id or settings.default_profile, settings.profiles_dir)
        account = broker.account_info()
        run = manager.create_run(
            profile,
            broker_name=broker.name,
            account=f"{account.login_masked}@{account.server}",
            initial_balance=account.balance,
        )
        manager.mark_ready(run, account)
    else:
        return None

    risk = RiskEngine(run.profile.risk)
    execution = ExecutionService(broker, risk, run, manager, journal, killswitch, clock=clk)
    monitor = PositionMonitor(broker, manager, journal, run)
    return Components(
        settings, run.profile, broker, repo, journal, manager, killswitch, run, risk, execution, monitor
    )
