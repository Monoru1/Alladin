from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from alladin.brokers.base import BrokerCapabilities
from alladin.brokers.crypto import CryptoMockProvider
from alladin.brokers.crypto_observe import CryptoObserveBroker
from alladin.challenge.models import UniverseRules
from alladin.core.enums import AssetCategory, Timeframe
from alladin.market.sessions import SessionRules, SessionWindow
from alladin.market.universe import MarketUniverse, classify_symbol
from alladin.research.r_analytics import CostCategory, CostModel, FundingSettlement, funding_cashflow
from tests.conftest import T0


@pytest.mark.parametrize("liquidity,rate", [("MAKER", -0.0001), ("TAKER", 0.001)])
def test_per_fill_fee_and_rebate_are_in_account_currency(liquidity, rate):
    model = CostModel(commission=CostCategory.MODELED, maker_rate=-0.0001, taker_rate=0.001,
                      fee_provenance="test schedule")
    assert model.fee(20000, liquidity) == pytest.approx(20000 * rate)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 0])
def test_fee_refuses_invalid_notional(value):
    model = CostModel(commission=CostCategory.MODELED, maker_rate=0, fee_provenance="explicit zero")
    with pytest.raises(ValueError):
        model.fee(value, "MAKER")


def test_unknown_fees_never_default_to_zero():
    with pytest.raises(ValueError, match="unknown"):
        CostModel().fee(1000, "TAKER")
    with pytest.raises(ValueError):
        CostModel(maker_rate=0.001)
    with pytest.raises(ValueError):
        CostModel(commission=CostCategory.MODELED, maker_rate=float("nan"), fee_provenance="fixture")


@pytest.mark.parametrize("side", [1, -1])
def test_funding_sign_time_window_and_varying_notional(side):
    model = CostModel(funding=CostCategory.OBSERVED)
    settlements = [
        FundingSettlement("open", T0, 0.001, 10000, "fixture"),
        FundingSettlement("first", T0 + timedelta(hours=8), 0.001, 10000, "fixture"),
        FundingSettlement("close", T0 + timedelta(hours=16), -0.002, 5000, "fixture"),
        FundingSettlement("after", T0 + timedelta(hours=24), 0.002, 5000, "fixture"),
    ]
    assert funding_cashflow(settlements, side_sign=side, opened_at=T0,
                            closed_at=T0 + timedelta(hours=16), model=model) == pytest.approx(0)
    assert funding_cashflow(settlements[:2], side_sign=side, opened_at=T0,
                            closed_at=T0 + timedelta(hours=16), model=model) == -side * 10
    with pytest.raises(ValueError, match="duplicate"):
        funding_cashflow([settlements[1]] * 2, side_sign=side, opened_at=T0,
                         closed_at=T0 + timedelta(hours=16), model=model)
    with pytest.raises(ValueError, match="not modeled"):
        funding_cashflow([], side_sign=side, opened_at=T0, closed_at=T0, model=CostModel())


@pytest.mark.parametrize("field,value", [("rate", float("nan")), ("notional_account", -1),
                                         ("provenance", ""), ("settled_at", T0.replace(tzinfo=None))])
def test_funding_requires_valid_observed_inputs(field, value):
    values = dict(settlement_id="s", settled_at=T0, rate=0.001, notional_account=1000, provenance="fixture")
    values[field] = value
    with pytest.raises(ValueError):
        FundingSettlement(**values)


def test_configured_windows_utc_conversion_and_24_7_capability():
    rules = SessionRules(timezone="Europe/Paris", weekdays=frozenset({0}),
                         windows=(SessionWindow(start_minute=9 * 60, end_minute=17 * 60),))
    assert rules.allows(T0)  # Monday 11:00 Paris
    assert not rules.allows(T0 + timedelta(days=5))
    assert not rules.allows(datetime(2026, 3, 2, 16, tzinfo=UTC))  # exclusive 17:00 Paris
    assert not SessionRules(require_24_7=True).allows(T0)
    assert SessionRules(require_24_7=True).allows(T0 + timedelta(days=5), is_24_7=True)
    with pytest.raises(ValueError):
        rules.allows(T0.replace(tzinfo=None))
    with pytest.raises(ValidationError):
        SessionWindow(start_minute=1320, end_minute=360)
    with pytest.raises(ValidationError):
        SessionRules(weekdays=frozenset({7}))


def test_crypto_category_requires_explicit_metadata_and_capability():
    broker = CryptoObserveBroker(CryptoMockProvider(start=T0))
    spec = broker.symbol_spec("BTCUSDT")
    assert spec and classify_symbol(spec) is AssetCategory.CRYPTO_SPOT
    assert classify_symbol(spec.model_copy(update={"category": AssetCategory.OTHER})) is AssetCategory.OTHER
    rules = UniverseRules(allowed_categories=[AssetCategory.CRYPTO_SPOT])
    assert len(MarketUniverse(broker, rules).discover().members) == 1
    broker.capabilities = lambda: BrokerCapabilities(name="no crypto")
    assert not MarketUniverse(broker, rules).discover().members


def test_data_adapter_never_claims_missing_fees_funding_or_execution():
    broker = CryptoObserveBroker(CryptoMockProvider(start=T0))
    caps = broker.capabilities()
    assert caps.is_24_7 and not caps.has_funding_rate and not caps.has_maker_taker_fees
    assert not caps.can_open_position and not caps.can_close_position
    assert broker.symbol_spec("ETHUSDT") is None
    with pytest.raises(ValueError):
        broker.bars("BTCUSDT", Timeframe.H1, 1001)
    assert all(b.close_time <= T0 for b in broker.bars("BTCUSDT", Timeframe.H1, 100))


def test_closed_session_blocks_direct_entry_but_allows_protective_close(svc):
    from alladin.core.enums import RunMode
    from tests.conftest import make_intent

    intent = make_intent(svc)
    assert svc.execution.submit(intent).executed
    position = svc.execution.owned_positions(RunMode.DEMO)[0]
    svc.run.profile.universe.sessions = SessionRules(weekdays=frozenset({6}))
    sent = len(svc.broker.sent_orders)
    refused = svc.execution.submit(make_intent(svc))
    assert refused.decision and not refused.decision.approved
    assert "SESSION_CLOSED" in {r.code.value for r in refused.decision.reasons}
    assert len(svc.broker.sent_orders) == sent
    assert svc.execution.close_position(position.broker_ticket, "protective close outside entry session")


def test_scanner_applies_session_before_fetch(svc):
    from alladin.market.scanner import MarketScanner

    rules = UniverseRules(sessions=SessionRules(weekdays=frozenset({6})))
    scanner = MarketScanner(svc.broker, MarketUniverse(svc.broker, rules), rules)
    svc.broker.bars = lambda *args: pytest.fail("bars fetched outside configured session")
    scan = scanner.scan()
    assert scan.analysed == 0 and not scan.candidates
    assert any("session" in reason for reasons in scan.rejected.values() for reason in reasons)


def test_funding_cashflow_flows_into_net_r_separately_from_swap():
    from alladin.research.r_analytics import compute_r

    metrics = compute_r(side_sign=1, entry=100, stop_loss=90, exit_price=110, opened_at=T0,
                        closed_at=T0 + timedelta(hours=8), price_value_per_lot=1,
                        commission=1, swap=-2, funding=-3)
    assert metrics.realized_r == pytest.approx(0.4)
    assert metrics.swap_r == pytest.approx(-0.2)
    assert metrics.funding_r == pytest.approx(-0.3)


def test_mock_bars_are_stable_across_count_clock_and_process():
    provider = CryptoMockProvider(start=T0 + timedelta(microseconds=123))
    old = provider.klines("BTCUSDT", Timeframe.H1, 10)
    assert all(b.time.microsecond == 0 for b in old)
    assert old[-5:] == provider.klines("BTCUSDT", Timeframe.H1, 5)
    provider.advance(3600)
    later = provider.klines("BTCUSDT", Timeframe.H1, 10)
    assert old[1:] == later[:-1]
    assert later == CryptoMockProvider(start=provider.now()).klines("BTCUSDT", Timeframe.H1, 10)
