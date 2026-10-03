from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

import alladin.cli as cli
from alladin.agents.mock import MockAgent
from alladin.api.app import create_app
from alladin.brokers.crypto import CryptoMockProvider
from alladin.brokers.crypto_observe import CryptoObserveBroker
from alladin.core.enums import AccountType, RunMode
from alladin.core.errors import AlladinError, ExecutionBlockedError
from alladin.core.workspace import WorkspaceId
from alladin.journal.repository import JournalRepository
from alladin.market.archive import MarketDataArchive
from alladin.orchestration.bootstrap import build_services
from alladin.replay import ReplayContext
from tests.conftest import T0, make_intent


@pytest.fixture
def jafar(settings):
    broker = CryptoObserveBroker(CryptoMockProvider(start=T0))
    svc = build_services(settings, broker, create_run=True, workspace=WorkspaceId.JAFAR)
    assert svc
    svc.manager.start(svc.run, broker.account_info())
    return svc


def test_observe_cycle_archives_crypto_without_strategy_or_order(jafar):
    assert jafar.run.workspace is WorkspaceId.JAFAR
    assert jafar.profile.id == "jafar_observe"
    assert jafar.broker.account_info().account_type is AccountType.UNKNOWN
    engine = jafar.engine(MockAgent())
    assert not engine.router.registry.enabled()
    outcome = engine.run_cycle()
    assert outcome.decision == "NO_TRADE" and "no strategy" in outcome.reason
    scan = jafar.repo.events(jafar.run.run_id, ["market.scan"])[0]
    assert scan.payload["analysed"] == 1
    archive = MarketDataArchive(jafar.repo.engine, workspace=WorkspaceId.JAFAR)
    assert archive.stats()["bars"] > 0
    replay = ReplayContext.from_cycle(jafar.repo, outcome.cycle_id)
    assert replay.workspace is WorkspaceId.JAFAR
    assert jafar.repo.verify_chain(jafar.run.run_id)[0]
    assert not jafar.repo.trades_for_run(jafar.run.run_id)


@pytest.mark.parametrize("mode", [RunMode.PAPER, RunMode.DEMO])
def test_jafar_modes_fail_closed(jafar, mode):
    with pytest.raises(AlladinError, match="OBSERVE"):
        jafar.engine(MockAgent(), run_mode=mode)
    with pytest.raises(AlladinError, match="OBSERVE"):
        jafar.engine(MockAgent(), execute=True)
    engine = jafar.engine(MockAgent())
    engine.run_mode = mode
    with pytest.raises(AlladinError, match="OBSERVE"):
        engine.run_cycle()
    assert not jafar.repo.trades_for_run(jafar.run.run_id)


def test_direct_execution_and_broker_methods_cannot_send(jafar):
    # Reference metadata supplies geometry for an intent but never execution rights.
    assert jafar.execution.submit(make_intent(jafar, symbol="BTCUSDT")).status.value == "BLOCKED"
    assert jafar.execution.close_all("no order") == 0
    from alladin.core.enums import OrderAction, Side
    from alladin.core.models import OrderRequest
    request = OrderRequest(action=OrderAction.OPEN, symbol="BTCUSDT", side=Side.BUY,
                           volume=0.001, magic=jafar.run.magic, comment="fixture")
    with pytest.raises(ExecutionBlockedError):
        jafar.broker.check_order(request)
    with pytest.raises(ExecutionBlockedError):
        jafar.broker._send(request)
    with pytest.raises(ExecutionBlockedError):
        jafar.broker.assert_demo()


def test_scoped_cockpit_is_red_readonly_and_identifies_virtual_budget(jafar):
    client = TestClient(create_app(jafar.settings, jafar.repo, jafar.broker))
    html = client.get("/").text
    assert "JAFAR Mission Control" in html and "--accent:#ef5350" in html
    assert "budget de référence virtuel" in html
    assert client.get("/api/strategies").json() == []
    health = client.get("/health").json()
    assert health["workspace"] == "JAFAR" and health["observe_only"] and not health["demo"]
    assert client.get("/api/workspace").json()["allowed_modes"] == ["OBSERVE"]
    assert client.get("/api/overview", params={"run_id": "RUN-001"}).status_code == 404
    assert client.get("/api/overview").json()["execution_blocked"]
    assert client.post("/api/overview").status_code == 405


def test_restart_uses_jafar_scopes_and_same_binding(jafar):
    engine = jafar.engine(MockAgent())
    engine.run_cycle()
    settings = jafar.settings
    resumed = build_services(settings, jafar.broker, workspace=WorkspaceId.JAFAR, run_id=jafar.run.run_id)
    assert resumed and resumed.run.run_id == jafar.run.run_id
    assert resumed.engine(MockAgent()).run_cycle().decision == "NO_TRADE"
    alladin = JournalRepository.from_url(resumed.settings.db_url, WorkspaceId.ALLADIN)
    assert alladin.list_runs() == []
    assert alladin.events(jafar.run.run_id) == []


def test_cli_new_run_kill_and_mode_rejection(settings, monkeypatch, tmp_path: Path):
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    runner = CliRunner()
    new = runner.invoke(cli.app, ["jafar", "new"])
    assert new.exit_code == 0, new.output
    result = runner.invoke(cli.app, ["jafar", "run", "--cycles", "1", "--interval", "0"])
    assert result.exit_code == 0 and "NO_TRADE" in result.output, result.output
    repo = JournalRepository.from_url(settings.for_workspace(WorkspaceId.JAFAR).db_url, WorkspaceId.JAFAR)
    run = repo.list_runs()[0]
    scan = repo.events(run.run_id, ["market.scan"])[0]
    assert scan.payload["analysed"] == 1 and scan.payload["archived_bars"] > 0
    blocked = runner.invoke(cli.app, ["jafar", "run", "--mode", "DEMO"])
    assert blocked.exit_code == 2 and "OBSERVE" in blocked.output
    kill = runner.invoke(cli.app, ["jafar", "kill"])
    assert kill.exit_code == 0, kill.output
    assert (tmp_path / "workspaces" / "JAFAR" / "KILL_SWITCH").exists()
    assert not settings.kill_switch_path.exists()
    clear = runner.invoke(cli.app, ["jafar", "kill", "--clear"])
    assert clear.exit_code == 0, clear.output
    assert not settings.for_workspace(WorkspaceId.JAFAR).kill_switch_path.exists()
    assert runner.invoke(cli.app, ["jafar", "new"]).exit_code == 0
    restarted = runner.invoke(cli.app, ["jafar", "run", "--cycles", "1", "--interval", "0"])
    assert restarted.exit_code == 0 and "RUN-JAFAR-002" in restarted.output, restarted.output


def test_direct_management_cannot_bypass_observe_gate(jafar):
    from alladin.brain import Action, ActionProposal, ProposalParameters, proposal_identity
    proposal = ActionProposal(
        proposal_id=proposal_identity(jafar.run.run_id, "cycle", "opp", "test", "1"),
        source_id="test", source_version="1", run_id=jafar.run.run_id, cycle_id="cycle",
        opportunity_id="opp", symbol="BTCUSDT", action=Action.CLOSE, timestamp=T0,
        parameters=ProposalParameters(position_id="nonexistent"))
    jafar.broker._send = lambda *args: pytest.fail("Jafar attempted order")
    assert jafar.execution.submit_position_action(proposal, RunMode.DEMO).status == "BLOCKED"


def test_scoped_serve_command_uses_jafar_app(settings, monkeypatch):
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    runner = CliRunner()
    assert runner.invoke(cli.app, ["jafar", "new"]).exit_code == 0
    captured = []
    import uvicorn
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: captured.append((app, kwargs)))
    served = runner.invoke(cli.app, ["jafar", "serve"])
    assert served.exit_code == 0, served.output
    app, options = captured[0]
    assert options["port"] == 8002 and options["host"] == "127.0.0.1"
    assert TestClient(app).get("/api/workspace").json()["workspace"] == "JAFAR"


def test_jafar_rejects_fx_profile_at_creation(settings):
    broker = CryptoObserveBroker(CryptoMockProvider(start=T0))
    with pytest.raises(AlladinError, match="profil"):
        build_services(settings, broker, workspace=WorkspaceId.JAFAR, create_run=True,
                       profile_id="ftmo_2step_demo")
