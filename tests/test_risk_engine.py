"""RiskEngine : rejets explicites, SL obligatoire, plafonds, exposition, corrélation, garde-fous."""

from __future__ import annotations

from datetime import timedelta

import pytest

from alladin.brokers.mock import MockBroker
from alladin.core.enums import AccountType, Side
from alladin.execution.models import ExecStatus
from alladin.orchestration.bootstrap import Components
from alladin.risk.correlation import CorrelationMatrix
from alladin.risk.models import RejectCode
from tests.conftest import make_intent


def codes(res) -> set[RejectCode]:  # type: ignore[no-untyped-def]
    assert res.decision is not None
    return {r.code for r in res.decision.reasons}


def test_approves_standard_trade_and_computes_volume(svc: Components) -> None:
    res = svc.execution.submit(make_intent(svc, risk_pct=4), dry_run=True)
    d = res.decision
    assert res.status is ExecStatus.DRY_RUN_APPROVED and d and d.approved and d.token is not None
    assert d.volume == 2.0
    assert d.risk_amount == pytest.approx(400)
    assert d.risk_pct_of_equity == pytest.approx(0.4)
    assert d.risk_pct_of_working_capital == pytest.approx(4.0)


def test_8_percent_is_a_ceiling_not_a_default(svc: Components) -> None:
    at_cap = svc.execution.submit(make_intent(svc, risk_pct=8), dry_run=True).decision
    assert at_cap and at_cap.approved and at_cap.risk_amount == pytest.approx(800, rel=1e-3)
    over = svc.execution.submit(make_intent(svc, risk_pct=9), dry_run=True)
    assert over.status is ExecStatus.REJECTED_RISK and RejectCode.RISK_EXCEEDS_CAP in codes(over)
    assert over.decision and over.decision.token is None and over.decision.volume == 0


def test_over_cap_can_be_clipped_when_profile_says_so(svc: Components) -> None:
    svc.risk.rules = svc.risk.rules.model_copy(update={"over_cap_policy": "clip"})
    res = svc.execution.submit(make_intent(svc, risk_pct=50), dry_run=True)
    assert res.decision and res.decision.approved
    assert res.decision.risk_amount <= 800 + 1e-6
    assert any("plafond" in a for a in res.decision.adjustments)


def test_no_stop_loss_is_rejected(svc: Components) -> None:
    res = svc.execution.submit(make_intent(svc, sl_pips=None), dry_run=True)
    assert res.status is ExecStatus.REJECTED_RISK
    assert RejectCode.NO_STOP_LOSS in codes(res)
    assert res.decision and "NO SL" in " ".join(res.decision.reason_lines())


def test_stop_loss_on_wrong_side_is_rejected(svc: Components) -> None:
    res = svc.execution.submit(make_intent(svc, sl_pips=-20), dry_run=True)  # SL au-dessus d'un BUY
    assert RejectCode.BAD_GEOMETRY in codes(res)


def test_expired_signal_is_rejected(svc: Components) -> None:
    res = svc.execution.submit(make_intent(svc, ttl=timedelta(seconds=-1)), dry_run=True)
    assert RejectCode.EXPIRED in codes(res)


def test_stale_entry_price_is_rejected(svc: Components) -> None:
    it = make_intent(svc, entry=1.2000)  # marché à 1.085 : l'agent annonce n'importe quoi
    assert RejectCode.PRICE_MOVED in codes(svc.execution.submit(it, dry_run=True))


def test_all_reasons_are_listed_not_just_the_first(svc: Components) -> None:
    it = make_intent(svc, sl_pips=None, risk_pct=50, ttl=timedelta(seconds=-1))
    res = svc.execution.submit(it, dry_run=True)
    assert {RejectCode.NO_STOP_LOSS, RejectCode.EXPIRED, RejectCode.RISK_EXCEEDS_CAP} <= codes(res)


def test_unknown_instrument_is_rejected(svc: Components) -> None:
    res = svc.execution.submit(
        make_intent(svc, symbol="EURUSD").model_copy(update={"instrument": "NOPE123"}), dry_run=True
    )
    assert res.status is ExecStatus.REJECTED_RISK


def test_currency_exposure_usd_bias_is_limited(svc: Components) -> None:
    """BUY EURUSD + BUY GBPUSD + SELL USDCHF = trois fois le même biais USD court."""
    r1 = svc.execution.submit(make_intent(svc, symbol="EURUSD", side=Side.BUY, risk_pct=8))
    assert r1.executed
    r2 = svc.execution.submit(make_intent(svc, symbol="GBPUSD", side=Side.BUY, risk_pct=8))
    assert r2.executed and r2.decision and r2.decision.adjustments  # réduit pour tenir sous le seuil USD
    assert r2.decision.risk_amount < 800
    r3 = svc.execution.submit(make_intent(svc, symbol="USDCHF", side=Side.SELL, risk_pct=8))
    assert r3.status is ExecStatus.REJECTED_RISK
    assert RejectCode.CURRENCY_EXPOSURE in codes(r3)
    assert any("USD exposure exceeds threshold" in m for m in r3.messages)


def test_opposite_direction_reduces_exposure_and_is_allowed(svc: Components) -> None:
    assert svc.execution.submit(make_intent(svc, symbol="EURUSD", side=Side.BUY, risk_pct=8)).executed
    # SELL GBPUSD = USD long : compense le biais USD court
    assert svc.execution.submit(make_intent(svc, symbol="GBPUSD", side=Side.SELL, risk_pct=8)).executed


def test_correlation_matrix_blocks_same_direction_correlated_pairs(svc: Components) -> None:
    cm = CorrelationMatrix()
    cm.set("EURUSD", "GBPUSD", 0.92)
    svc.execution.correlations = lambda: cm
    assert svc.execution.submit(make_intent(svc, symbol="EURUSD", side=Side.BUY, risk_pct=1)).executed
    res = svc.execution.submit(make_intent(svc, symbol="GBPUSD", side=Side.BUY, risk_pct=1))
    assert RejectCode.CORRELATION in codes(res)
    # sens opposé : pas de conflit de corrélation
    assert svc.execution.submit(make_intent(svc, symbol="GBPUSD", side=Side.SELL, risk_pct=1)).executed


def test_max_open_positions(svc: Components) -> None:
    svc.risk.rules = svc.risk.rules.model_copy(update={"max_open_positions": 1})
    assert svc.execution.submit(make_intent(svc, symbol="EURUSD", risk_pct=1)).executed
    assert RejectCode.MAX_POSITIONS in codes(
        svc.execution.submit(make_intent(svc, symbol="AUDUSD", risk_pct=1), dry_run=True)
    )


def test_hedging_forbidden_by_default(svc: Components) -> None:
    assert svc.execution.submit(make_intent(svc, risk_pct=1)).executed
    res = svc.execution.submit(make_intent(svc, side=Side.SELL, risk_pct=1), dry_run=True)
    assert RejectCode.HEDGING in codes(res)


def test_daily_headroom_insufficient_is_reported(svc: Components, broker: MockBroker) -> None:
    broker.inject_pnl(-4_900)  # equity 95 100 : 100 $ avant la perte journalière maximale
    res = svc.execution.submit(make_intent(svc, risk_pct=8), dry_run=True)
    assert res.status is ExecStatus.REJECTED_RISK
    assert RejectCode.DAILY_HEADROOM in codes(res)
    assert any("remaining daily loss headroom insufficient" in m for m in res.messages)


def test_risk_is_reduced_to_fit_remaining_headroom(svc: Components, broker: MockBroker) -> None:
    svc.profile.extra_rules.soft_daily_loss_pct = None  # on isole la règle officielle
    broker.inject_pnl(-4_300)  # equity 95 700 -> 700 de marge avant 95 000, moins 250 de tampon = 450
    res = svc.execution.submit(make_intent(svc, risk_pct=8), dry_run=True)
    assert res.decision and res.decision.approved
    assert res.decision.risk_amount == pytest.approx(450, abs=1)  # bien sous le plafond par trade (~765)
    assert any("daily loss headroom" in a for a in res.decision.adjustments)


def test_margin_limit(svc: Components) -> None:
    svc.risk.rules = svc.risk.rules.model_copy(update={"max_margin_usage_pct": 1})
    res = svc.execution.submit(make_intent(svc, risk_pct=8), dry_run=True)
    assert RejectCode.MARGIN in codes(res)


def test_spread_too_wide_relative_to_stop(svc: Components) -> None:
    res = svc.execution.submit(make_intent(svc, symbol="USDTRY", sl_pips=2, tp_pips=4), dry_run=True)
    assert RejectCode.SPREAD_TOO_WIDE in codes(res)


def test_stops_too_close_to_market(svc: Components) -> None:
    res = svc.execution.submit(make_intent(svc, sl_pips=0.5, tp_pips=50), dry_run=True)  # < stops_level
    assert RejectCode.STOPS_TOO_CLOSE in codes(res)


def test_kill_switch_blocks_everything(svc: Components) -> None:
    svc.killswitch.activate("test")
    res = svc.execution.submit(make_intent(svc), dry_run=True)
    assert RejectCode.KILL_SWITCH in codes(res)


@pytest.mark.parametrize(
    ("account_type", "message"),
    [
        (AccountType.LIVE, "LIVE ACCOUNT DETECTED — EXECUTION BLOCKED"),
        (AccountType.UNKNOWN, "ACCOUNT TYPE UNKNOWN — EXECUTION BLOCKED"),
        (AccountType.CONTEST, "ACCOUNT TYPE UNKNOWN — EXECUTION BLOCKED"),
    ],
)
def test_non_demo_account_blocks_execution_and_sends_nothing(
    svc: Components, broker: MockBroker, account_type: AccountType, message: str
) -> None:
    broker.set_account_type(account_type)
    res = svc.execution.submit(make_intent(svc))
    assert res.status is ExecStatus.BLOCKED
    assert message in res.messages[0]
    assert broker.sent_orders == [] and broker.positions() == []
