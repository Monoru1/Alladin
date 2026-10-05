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
from alladin.brain import Brain
from alladin.brokers.base import BrokerAdapter
from alladin.brokers.binance import BinanceRestClient, Ed25519PemSigner
from alladin.brokers.crypto import BinancePublicProvider, CryptoMockProvider
from alladin.brokers.crypto_observe import CryptoObserveBroker
from alladin.brokers.mock import MockBroker
from alladin.brokers.mt5 import MT5Broker
from alladin.challenge.models import ChallengeProfile
from alladin.challenge.profiles import load_profile
from alladin.core.config import Settings
from alladin.core.enums import JafarMode, RunMode
from alladin.core.errors import AlladinError
from alladin.core.killswitch import KillSwitch
from alladin.core.workspace import AccountBinding, WorkspaceId
from alladin.execution.order_lifecycle import (
    JafarStartupReconciler,
    OrderLifecycleRepository,
    ReconciliationReport,
)
from alladin.execution.service import ExecutionService
from alladin.journal.models import EventType
from alladin.journal.repository import JournalRepository
from alladin.journal.service import JournalService
from alladin.market.archive import MarketDataArchive
from alladin.market.paper import PaperExperimentEngine
from alladin.market.scanner import MarketScanner
from alladin.market.universe import MarketUniverse
from alladin.orchestration.engine import OrchestrationEngine
from alladin.orchestration.monitor import PositionMonitor
from alladin.orchestration.state import RunContext, RunManager
from alladin.research.models import StrategyStatus
from alladin.research.outcomes import OutcomeEngine, RewardPolicy
from alladin.research.repository import ResearchRepository
from alladin.research.snn.shadow_brain import ShadowBrain, ShadowSNN
from alladin.risk.engine import RiskEngine
from alladin.strategies.registry import StrategyRegistry
from alladin.strategies.router import StrategyRouter


def make_broker(kind: str, settings: Settings, profile: ChallengeProfile | None = None) -> BrokerAdapter:
    if kind in ("crypto-mock", "crypto-public", "crypto-testnet"):
        provider = (
            CryptoMockProvider()
            if kind == "crypto-mock"
            else BinancePublicProvider(testnet=kind == "crypto-testnet")
        )
        return CryptoObserveBroker(
            provider,
            provenance=f"crypto:{kind}",
            max_symbols=25 if kind != "crypto-mock" else None,
        )
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


def make_binance_account_client(settings: Settings, *, testnet: bool = False) -> BinanceRestClient:
    """Construit l'acces USER_DATA read-only ; aucun endpoint d'ordre n'existe sur ce client."""
    api_key = settings.binance_api_key.get_secret_value() if settings.binance_api_key else None
    key_path = settings.jafar_binance_private_key_path
    if not api_key or key_path is None:
        raise AlladinError("BINANCE_API_KEY et JAFAR_BINANCE_PRIVATE_KEY_PATH requis")
    return BinanceRestClient(
        testnet=testnet,
        api_key=api_key,
        signer=Ed25519PemSigner(key_path),
        recv_window_ms=settings.binance_recv_window_ms,
    )


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
    outcomes: OutcomeEngine
    jafar_mode: JafarMode | None = None
    order_lifecycle: OrderLifecycleRepository | None = None
    startup_reconciliation: ReconciliationReport | None = None

    def engine(
        self,
        agent: AgentAdapter,
        *,
        execute: bool = False,
        run_mode: RunMode = RunMode.OBSERVE,
        brain: Brain | None = None,
    ) -> OrchestrationEngine:
        shadow_brains: tuple[ShadowBrain, ...] = ()
        if self.run.workspace is WorkspaceId.JAFAR:
            if execute or run_mode is not RunMode.OBSERVE:
                raise AlladinError("Jafar skeleton autorise OBSERVE uniquement")
            from alladin.orchestration.jafar import JafarObserveBrain

            registry = StrategyRegistry()  # no inherited FX strategies
            brain = brain or JafarObserveBrain()
            if isinstance(self.broker, CryptoObserveBroker):
                self.journal.log(
                    self.run.run_id, EventType.UNIVERSE, self.broker.universe_summary()
                )
            shadow_brains = (
                ShadowBrain(
                    shadow_id="jafar-k2",
                    journal_path=self.settings.resolved_data_dir / "shadow" / f"{self.run.run_id}.json",
                    snn=ShadowSNN(seed=42),
                ),
            )
        else:
            registry = StrategyRegistry.from_config(self.settings.strategies_dir)
        effective_mode = RunMode.DEMO if execute and run_mode is RunMode.OBSERVE else run_mode
        if effective_mode in (RunMode.DEMO, RunMode.PAPER):
            versions = ResearchRepository.from_engine(self.repo.engine, self.run.workspace).list_versions()
            approved = {
                f"{v.strategy_id}@{v.version}" for v in versions if v.status is StrategyStatus.APPROVED
            }
            if effective_mode is RunMode.DEMO:
                registry.check_lifecycle(approved, strict=True)
            else:
                registry.check_paper_lifecycle(approved)
        universe = MarketUniverse(self.broker, self.profile.universe)
        scanner = MarketScanner(
            self.broker,
            universe,
            self.profile.universe,
            archive=MarketDataArchive(self.repo.engine, workspace=self.run.workspace),
        )
        router = StrategyRouter(registry, performance=self.journal)
        paper_engine: PaperExperimentEngine | None = None
        if effective_mode is RunMode.PAPER:
            paper_engine = PaperExperimentEngine(self.broker, self.run.run_id, repo=self.repo)
            paper_engine.restore()
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
            run_mode=run_mode,
            execute=execute,
            paper_engine=paper_engine,
            brain=brain,
            outcomes=self.outcomes,
            shadow_brains=shadow_brains,
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
    run_kind: str = "RUN",
    workspace: WorkspaceId = WorkspaceId.ALLADIN,
) -> Components | None:
    """Retourne None si aucun run n'existe et que `create_run` est faux."""
    workspace = WorkspaceId(workspace)
    settings = settings.for_workspace(workspace)
    repo = JournalRepository.from_url(db_url or settings.db_url, workspace)
    clk = clock or broker.now
    journal = JournalService(repo, clk)
    killswitch = KillSwitch(killswitch_path or settings.kill_switch_path)
    manager = RunManager(repo, journal, killswitch, settings.magic_base, clk)

    existing = run_id or manager.latest_run_id(only_open=True, kind=run_kind)
    if existing and not create_run:
        rec = repo.get_run(existing)
        if rec is None:
            repo.close()
            raise AlladinError(f"run introuvable : {existing}")
        profile = load_profile(rec.profile_id, settings.profiles_dir)
        run = manager.load_run(existing, profile)
    elif create_run:
        if workspace is WorkspaceId.JAFAR and profile_id not in (None, "jafar_observe"):
            raise AlladinError("Jafar skeleton exige le profil jafar_observe")
        profile = load_profile(profile_id or settings.default_profile, settings.profiles_dir)
        account = broker.account_info()
        run = manager.create_run(
            profile,
            broker_name=broker.name,
            account=f"{account.login_masked}@{account.server}",
            initial_balance=account.balance,
            kind=run_kind,
            account_binding=AccountBinding(
                workspace=workspace,
                broker=broker.name,
                account_ref=account.login_masked,
                server=account.server,
                account_type=account.account_type,
                account_fingerprint=account.account_fingerprint,
            ),
        )
        manager.mark_ready(run, account)
    else:
        return None

    snapshot = broker.account_info()
    expected_account = f"{snapshot.login_masked}@{snapshot.server}"
    if run.broker_name != broker.name or repo.get_run(run.run_id).account != expected_account:  # type: ignore[union-attr]
        raise AlladinError("broker/compte différent du binding persisté : reprise refusée")
    if (
        run.account_binding
        and run.account_binding.account_fingerprint is not None
        and run.account_binding.account_fingerprint != snapshot.account_fingerprint
    ):
        raise AlladinError("empreinte de compte différente du binding persisté")
    risk = RiskEngine(run.profile.risk)
    execution = ExecutionService(broker, risk, run, manager, journal, killswitch, clock=clk)
    monitor = PositionMonitor(broker, manager, journal, run)
    components = Components(
        settings,
        run.profile,
        broker,
        repo,
        journal,
        manager,
        killswitch,
        run,
        risk,
        execution,
        monitor,
        OutcomeEngine(repo, journal, RewardPolicy.load(settings.reward_policy_path)),
    )
    if workspace is WorkspaceId.JAFAR:
        from alladin.orchestration.jafar import JafarModeStore

        components.jafar_mode = JafarModeStore(journal, run.run_id).load()
        components.order_lifecycle = OrderLifecycleRepository(repo.engine, WorkspaceId.JAFAR)
        pending = components.order_lifecycle.pending_reconciliation()
        if pending:
            try:
                client = make_binance_account_client(
                    settings, testnet=broker.account_info().server == "crypto:crypto-testnet"
                )
                client.account()
                client.open_orders()
                report = JafarStartupReconciler(
                    components.order_lifecycle, client.query_order
                ).reconcile()
            except Exception as exc:
                report = ReconciliationReport(
                    coherent=False,
                    inspected=len(pending),
                    resolved=0,
                    ambiguous=tuple(claim.client_order_id for claim in pending),
                    errors=(type(exc).__name__,),
                )
            components.startup_reconciliation = report
            journal.log(run.run_id, EventType.RECONCILE, report.model_dump(mode="json"))
            if not report.coherent:
                raise AlladinError("reconciliation Jafar ambigue: reprise fail-closed")
        else:
            components.startup_reconciliation = ReconciliationReport(
                coherent=True, inspected=0, resolved=0
            )
    return components
