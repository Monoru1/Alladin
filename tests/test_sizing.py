"""Enveloppe de travail (10 % equity), plafond par trade (8 % du capital de travail), sizing."""

from __future__ import annotations

import pytest

from alladin.brokers.mock import MockBroker
from alladin.orchestration.bootstrap import Components
from alladin.risk.sizing import PositionSizer, floor_to_step, loss_per_lot, max_trade_risk, working_capital
from tests.conftest import make_intent


def test_working_capital_is_10_percent_of_equity() -> None:
    assert working_capital(100_000, 10) == 10_000


def test_max_trade_risk_is_8_percent_of_working_capital() -> None:
    wc = working_capital(100_000, 10)
    assert max_trade_risk(wc, 8) == 800  # = 0,8 % de l'equity


@pytest.mark.parametrize(
    ("equity", "wc", "max_risk"),
    [(100_000, 10_000, 800), (105_000, 10_500, 840), (95_000, 9_500, 760)],
)
def test_capacity_follows_equity(equity: float, wc: float, max_risk: float) -> None:
    w = working_capital(equity, 10)
    assert w == pytest.approx(wc)
    assert max_trade_risk(w, 8) == pytest.approx(max_risk)


def test_loss_per_lot_eurusd(broker: MockBroker) -> None:
    spec = broker.symbol_spec("EURUSD")
    assert spec is not None
    assert loss_per_lot(spec, 1.1000, 1.0980) == pytest.approx(200.0)  # 20 pips * 10 $/pip/lot


def test_position_sizing_risk_400_gives_2_lots(broker: MockBroker) -> None:
    spec = broker.symbol_spec("EURUSD")
    assert spec is not None
    res = PositionSizer().size(spec, 1.1000, 1.0980, 400)
    assert res.volume == 2.0
    assert res.actual_risk == pytest.approx(400)


def test_sizing_floors_to_volume_step_never_exceeds_risk(broker: MockBroker) -> None:
    spec = broker.symbol_spec("EURUSD")
    assert spec is not None
    res = PositionSizer().size(spec, 1.1000, 1.0980, 405)  # 2.025 lots -> 2.02
    assert res.volume == 2.02
    assert res.actual_risk <= 405


def test_sizing_refuses_when_min_volume_exceeds_allowed_risk(broker: MockBroker) -> None:
    spec = broker.symbol_spec("EURUSD")
    assert spec is not None
    res = PositionSizer().size(spec, 1.1000, 1.0980, 1.0)  # 0,005 lot < volume_min 0,01
    assert res.volume == 0 and res.reason


def test_jpy_pair_uses_account_currency_tick_value(broker: MockBroker) -> None:
    spec = broker.symbol_spec("USDJPY")
    assert spec is not None
    # 20 pips sur USDJPY = 0,20 ; tick_value USD = 0,001*100000/150 ≈ 0,667 par tick de 0,001
    lpl = loss_per_lot(spec, 150.00, 149.80)
    assert lpl == pytest.approx(0.20 / 0.001 * spec.trade_tick_value)
    assert 130 < lpl < 140


def test_floor_to_step_absorbs_float_noise() -> None:
    assert floor_to_step(1.9999999999999998, 0.01) == 2.0
    assert floor_to_step(0.0299, 0.01) == 0.02


def test_risk_shrinks_when_equity_falls_and_grows_when_it_rises(svc: Components) -> None:
    b: MockBroker = svc.broker  # type: ignore[assignment]
    base = svc.execution.submit(make_intent(svc, risk_pct=8), dry_run=True).decision
    assert base and base.approved and base.max_trade_risk == pytest.approx(800, rel=1e-3)

    b.inject_pnl(-2_000)  # equity 98 000 (sous le blocage souple de 3 % : on reste au-dessus)
    lower = svc.execution.submit(make_intent(svc, risk_pct=8), dry_run=True).decision
    assert lower and lower.approved
    assert lower.working_capital == pytest.approx(9_800)
    assert lower.max_trade_risk == pytest.approx(784)
    assert lower.volume < base.volume

    b.inject_pnl(+9_000)  # equity 107 000
    higher = svc.execution.submit(make_intent(svc, risk_pct=8), dry_run=True).decision
    assert higher and higher.approved
    assert higher.max_trade_risk == pytest.approx(856)
    assert higher.volume > base.volume
