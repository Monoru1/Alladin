"""CLI : démo, mt5 status, mt5 test-order (garde-fous DEMO + confirmation explicite), kill."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

import alladin.cli as cli
from alladin.brokers.mt5 import MT5Broker
from alladin.core.config import Settings
from tests.fake_mt5 import FakeMT5

runner = CliRunner()


@pytest.fixture
def cli_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    st = Settings(ALLADIN_DATA_DIR=str(tmp_path), _env_file=None)  # type: ignore[call-arg]
    monkeypatch.setattr(cli, "get_settings", lambda: st)
    return st


def use_fake(monkeypatch: pytest.MonkeyPatch, fake: FakeMT5) -> FakeMT5:
    monkeypatch.setattr(cli, "make_broker", lambda kind, settings, profile=None: MT5Broker(mt5_module=fake))
    return fake


def test_demo_shows_the_lab_header() -> None:
    res = runner.invoke(cli.app, ["demo"])
    assert res.exit_code == 0, res.output
    for needle in ("ALLADIN LAB", "RUN: RUN-001", "MODE: DEMO", "$100,000", "$10,000", "$800", "Broker:", "MOCK", "STATUS: READY",
                   "APPROVED", "NO SL", "NO_TRADE", "correlated USD exposure exceeds threshold", "OK —"):  # fmt: skip
        assert needle in res.output, needle


def test_demo_fail_and_pass_scenarios() -> None:
    fail = runner.invoke(cli.app, ["demo", "--scenario", "fail"])
    assert (
        "run FAILED" in fail.output
        and "état terminal" in fail.output
        and "Run RUN-001: FAILED" in fail.output
    )
    ok = runner.invoke(cli.app, ["demo", "--scenario", "pass"])
    assert (
        "PHASE 1 VALIDÉE" in ok.output
        and "CHALLENGE PASSED" in ok.output
        and "Run RUN-001: PASSED" in ok.output
    )


def test_mt5_status_demo(cli_env: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    use_fake(monkeypatch, FakeMT5())
    res = runner.invoke(cli.app, ["mt5", "status"])
    assert res.exit_code == 0, res.output
    for needle in ("ALLADIN — MT5 CONNECTION", "Terminal: CONNECTED", "Account: *****678", "Mode: DEMO", "Server: Acme-Demo",
                   "Currency: USD", "Balance: $50,000", "Symbols discovered: 3", "Open positions: 0", "ALLADIN STATUS: READY"):  # fmt: skip
        assert needle in res.output, needle
    assert "12345678" not in res.output


def test_mt5_status_not_connected_tells_exactly_what_to_do(
    cli_env: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_fake(monkeypatch, FakeMT5(init_ok=False))
    res = runner.invoke(cli.app, ["mt5", "status"])
    assert res.exit_code == 1
    assert (
        "NOT CONNECTED" in res.output
        and "CE QUI MANQUE" in res.output
        and "python -m alladin mt5 status" in res.output
    )


def test_mt5_status_live_account_is_flagged(cli_env: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    use_fake(monkeypatch, FakeMT5(trade_mode=2, server="Acme-Live"))
    res = runner.invoke(cli.app, ["mt5", "status"])
    assert res.exit_code == 3 and "LIVE ACCOUNT DETECTED — EXECUTION BLOCKED" in res.output


def test_test_order_refuses_live_account_even_if_user_types_execute(
    cli_env: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = use_fake(monkeypatch, FakeMT5(trade_mode=2, server="Acme-Live"))
    res = runner.invoke(cli.app, ["mt5", "test-order"], input="y\nEXECUTE\n")
    assert res.exit_code == 3 and "LIVE ACCOUNT DETECTED — EXECUTION BLOCKED" in res.output
    assert fake.order_send_calls == [] and fake.order_check_calls == []


def test_test_order_refuses_unknown_account_type(cli_env: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = use_fake(monkeypatch, FakeMT5(trade_mode=7))
    res = runner.invoke(cli.app, ["mt5", "test-order"], input="y\nEXECUTE\n")
    assert (
        res.exit_code == 3
        and "ACCOUNT TYPE UNKNOWN — EXECUTION BLOCKED" in res.output
        and fake.order_send_calls == []
    )


def test_test_order_stops_with_exit_6_when_algo_trading_is_off(
    cli_env: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = use_fake(monkeypatch, FakeMT5(trade_allowed=False))
    res = runner.invoke(cli.app, ["mt5", "test-order"], input="y\nEXECUTE\n")
    assert res.exit_code == 6
    assert "Activez Algo Trading" in res.output
    assert fake.order_check_calls == [] and fake.order_send_calls == []


@pytest.mark.parametrize("answer", ["", "yes", "execute", "oui", "n"])
def test_test_order_sends_nothing_without_the_explicit_word(
    cli_env: Settings, monkeypatch: pytest.MonkeyPatch, answer: str
) -> None:
    fake = use_fake(monkeypatch, FakeMT5())
    res = runner.invoke(cli.app, ["mt5", "test-order"], input=f"y\n{answer}\n")
    assert "RÉCAPITULATIF" in res.output and "RISK ENGINE: APPROVED" in res.output
    assert "Annulé : aucun ordre envoyé" in res.output and fake.order_send_calls == []


def test_test_order_no_input_at_all_sends_nothing(cli_env: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = use_fake(monkeypatch, FakeMT5())
    runner.invoke(cli.app, ["mt5", "test-order"], input="")  # stdin fermé (non interactif)
    assert fake.order_send_calls == []


def test_test_order_full_pipeline_after_explicit_confirmation(
    cli_env: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = use_fake(monkeypatch, FakeMT5())
    res = runner.invoke(cli.app, ["mt5", "test-order", "--symbol", "EURUSD"], input="y\nEXECUTE\n")
    assert res.exit_code == 0, res.output
    assert (
        "ORDER ACCEPTED" in res.output
        and "retcode: 10009" in res.output
        and "ticket/position:" in res.output
        and "positions_get" in res.output
    )
    (sent,) = fake.order_send_calls
    assert sent["volume"] == 0.01  # volume minimum, calculé par le PositionSizer
    assert (
        sent["sl"]
        and sent["tp"]
        and sent["magic"] > 26_000_000
        and sent["comment"].startswith("ALD-S-")
    )
    # l'ordre est enregistré dans ALLADIN
    from alladin.journal.repository import JournalRepository

    repo = JournalRepository.from_url(cli_env.db_url)
    (trade,) = repo.trades_for_run("SYSTEM-TEST-001", "OPEN")
    assert trade.symbol == "EURUSD" and trade.strategy_id == "TEST-00" and trade.volume == 0.01
    assert repo.verify_chain("SYSTEM-TEST-001")[0]
    assert [r.kind for r in repo.list_runs()] == ["SYSTEM-TEST"]  # aucun RUN officiel pollué par le test


def test_test_order_unknown_symbol(cli_env: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = use_fake(monkeypatch, FakeMT5())
    res = runner.invoke(cli.app, ["mt5", "test-order", "--symbol", "NOPE"], input="y\n")
    assert res.exit_code == 2 and "introuvable" in res.output and fake.order_send_calls == []


def test_challenge_status_preview_without_run(cli_env: Settings) -> None:
    res = runner.invoke(cli.app, ["challenge", "status", "--broker", "mock"])
    assert res.exit_code == 0, res.output
    for needle in (
        "CHALLENGE STATUS",
        "Working capital",
        "$10,000",
        "Max trade risk",
        "$800",
        "Daily loss headroom",
        "Total loss headroom",
        "Phase:",
        "+10 %",
    ):
        assert needle in res.output, needle


def test_kill_switch_command(cli_env: Settings) -> None:
    from alladin.brokers.mock import MockBroker
    from alladin.journal.repository import JournalRepository
    from alladin.orchestration.bootstrap import build_services

    comps = build_services(cli_env, MockBroker(), create_run=True)
    assert comps is not None
    res = runner.invoke(cli.app, ["kill", "--reason", "test"])
    assert res.exit_code == 0 and "KILLED : RUN-001" in res.output
    assert cli_env.kill_switch_path.exists()
    assert JournalRepository.from_url(cli_env.db_url).get_run("RUN-001").state == "KILLED"  # type: ignore[union-attr]
    runner.invoke(cli.app, ["kill", "--clear"])
    assert not cli_env.kill_switch_path.exists()
    assert (
        JournalRepository.from_url(cli_env.db_url).get_run("RUN-001").state == "KILLED"
    )  # un run KILLED le reste
