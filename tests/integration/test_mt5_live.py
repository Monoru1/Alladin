"""Intégration MT5 RÉEL (lecture seule). Exécuter avec : pytest --run-mt5

Nécessite un terminal MetaTrader 5 ouvert et connecté à un compte DEMO. N'envoie JAMAIS d'ordre.
"""

from __future__ import annotations

import pytest

from alladin.brokers.mt5 import MT5Broker
from alladin.core.enums import AccountType, Timeframe

pytestmark = pytest.mark.mt5_integration


@pytest.fixture(scope="module")
def mt5():  # type: ignore[no-untyped-def]
    b = MT5Broker()
    b.connect()
    yield b
    b.disconnect()


def test_account_is_demo_and_readable(mt5: MT5Broker) -> None:
    acct = mt5.account_info()
    assert acct.account_type is AccountType.DEMO, "ces tests exigent un compte DEMO"
    assert acct.equity > 0 and acct.currency


def test_symbols_discovered_dynamically(mt5: MT5Broker) -> None:
    specs = mt5.list_symbols()
    assert len(specs) > 0 and any(s.volume_step > 0 for s in specs)


def test_market_data_for_a_tradable_forex_symbol(mt5: MT5Broker) -> None:
    sym = next(s for s in mt5.list_symbols() if s.category.value.startswith("FOREX") and s.is_tradable)
    spec = mt5.symbol_spec(sym.symbol)
    assert spec and spec.trade_tick_size > 0
    for tf in (Timeframe.M1, Timeframe.H1, Timeframe.D1):
        assert len(mt5.bars(sym.symbol, tf, 50)) > 10
    assert mt5.tick(sym.symbol) is not None
