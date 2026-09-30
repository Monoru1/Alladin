"""Fixtures communes. Aucun test (hors marqueur mt5_integration) ne nécessite MetaTrader 5."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from alladin.brokers.mock import MockBroker
from alladin.challenge.models import ChallengeProfile
from alladin.challenge.profiles import load_profile
from alladin.core.config import REPO_ROOT, Settings
from alladin.core.enums import EntryType, MarketRegime, Side
from alladin.core.models import TradeIntent
from alladin.orchestration.bootstrap import Components, build_services

T0 = datetime(2026, 3, 2, 10, 0, tzinfo=UTC)  # lundi 10:00 UTC


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-mt5", action="store_true", help="exécuter les tests d'intégration MT5 (compte DEMO requis)"
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-mt5"):
        return
    skip = pytest.mark.skip(reason="intégration MT5 : passer --run-mt5 (terminal connecté à un compte DEMO)")
    for item in items:
        if "mt5_integration" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def profile() -> ChallengeProfile:
    return load_profile("ftmo_2step_demo", REPO_ROOT / "config" / "challenge_profiles")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(ALLADIN_DATA_DIR=str(tmp_path), _env_file=None)  # type: ignore[call-arg]


@pytest.fixture
def broker() -> MockBroker:
    return MockBroker(balance=100_000.0, start=T0)


@pytest.fixture
def svc(settings: Settings, broker: MockBroker) -> Components:
    comps = build_services(settings, broker, create_run=True, db_url="sqlite://")
    assert comps is not None
    comps.manager.start(comps.run, broker.account_info())
    return comps


def make_intent(
    comps: Components,
    *,
    symbol: str = "EURUSD",
    side: Side = Side.BUY,
    risk_pct: float = 4.0,
    sl_pips: float | None = 20,
    tp_pips: float | None = 50,
    strategy_id: str = "TREND-01",
    ttl: timedelta = timedelta(minutes=10),
    **over: object,
) -> TradeIntent:
    b = comps.broker
    tick = b.tick(symbol)
    assert tick is not None
    spec = b.symbol_spec(symbol)
    assert spec is not None
    pip = spec.point * 10
    px = tick.ask if side is Side.BUY else tick.bid
    d = side.sign
    now = b.now()
    data: dict[str, object] = dict(
        run_id=comps.run.run_id, agent="test", instrument=symbol, side=side, strategy_id=strategy_id,
        strategy_version="1.0.0", market_regime=MarketRegime.TREND, entry_type=EntryType.MARKET, entry=px,
        stop_loss=None if sl_pips is None else round(px - d * sl_pips * pip, spec.digits),
        take_profit=None if tp_pips is None else round(px + d * tp_pips * pip, spec.digits),
        requested_risk_pct_of_working_capital=risk_pct, confidence=0.7, reason="test",
        created_at=now, expires_at=now + ttl,
    )  # fmt: skip
    data.update(over)
    return TradeIntent(**data)  # type: ignore[arg-type]
