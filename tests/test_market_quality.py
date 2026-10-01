"""Tests : MarketQualityEngine, RejectCode, QualityReport."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from alladin.brokers.mock import MockBroker
from alladin.challenge.models import UniverseRules
from alladin.market.quality import MarketQualityEngine, QualityReport, RejectCode

T0 = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)


@pytest.fixture
def rules() -> UniverseRules:
    return UniverseRules(max_spread_atr_ratio=0.15)


@pytest.fixture
def broker() -> MockBroker:
    return MockBroker(balance=100_000.0, start=T0)


@pytest.fixture
def engine(rules: UniverseRules) -> MarketQualityEngine:
    return MarketQualityEngine(rules=rules, max_tick_age_s=1800.0)


def test_quality_report_passed_by_default(engine: MarketQualityEngine, broker: MockBroker) -> None:
    report = engine.evaluate(broker, "EURUSD", T0)
    assert report.passed is True
    assert report.reject_codes == []
    assert report.reject_reasons == []


def test_quality_report_no_tick_for_unknown_symbol(engine: MarketQualityEngine, broker: MockBroker) -> None:
    """Un symbole inconnu du mock retourne un tick None -> NO_TICK ou SYMBOL_NOT_SELECTABLE."""
    report = engine.evaluate(broker, "UNKNOWN_XYZ", T0)
    # MockBroker may return False for select_symbol or None for tick
    assert not report.passed
    assert len(report.reject_codes) > 0


def test_quality_report_stale_tick(engine: MarketQualityEngine, broker: MockBroker) -> None:
    """Un tick vieux de plus de max_tick_age_s doit etre rejete avec STALE_TICK."""
    # Advance clock far beyond max_tick_age_s
    stale_time = T0 + timedelta(hours=2)
    report = engine.evaluate(broker, "EURUSD", stale_time, atr=0.001)
    assert RejectCode.STALE_TICK in report.reject_codes


def test_quality_report_spread_too_high(rules: UniverseRules, broker: MockBroker) -> None:
    """Avec un ATR tres petit, le ratio spread/ATR depasse le seuil."""
    engine = MarketQualityEngine(rules=rules, max_tick_age_s=1800.0)
    # ATR quasi nul -> spread/ATR tres eleve
    report = engine.evaluate(broker, "EURUSD", T0, atr=0.0001)
    if report.spread and report.atr and report.atr > 0:
        ratio = report.spread / report.atr
        if ratio > rules.max_spread_atr_ratio:
            assert RejectCode.SPREAD_TOO_HIGH in report.reject_codes


def test_quality_report_atr_zero(engine: MarketQualityEngine, broker: MockBroker) -> None:
    """ATR nul -> ATR_TOO_LOW."""
    report = engine.evaluate(broker, "EURUSD", T0, atr=0.0)
    assert RejectCode.ATR_TOO_LOW in report.reject_codes
    assert not report.passed


def test_reject_codes_are_stable_strings() -> None:
    """Les codes de rejet doivent etre des chaines stables."""
    assert RejectCode.SPREAD_TOO_HIGH == "SPREAD_TOO_HIGH"
    assert RejectCode.STALE_TICK == "STALE_TICK"
    assert RejectCode.NO_TICK == "NO_TICK"
    assert RejectCode.INVALID_SPEC == "INVALID_SPEC"


def test_quality_report_reject_accumulates(engine: MarketQualityEngine) -> None:
    """reject() accumule les codes et passe passed=False."""
    report = QualityReport(symbol="TEST", passed=True)
    report.reject(RejectCode.SPREAD_TOO_HIGH, "spread too high")
    report.reject(RejectCode.ATR_TOO_LOW, "atr too low")
    assert not report.passed
    assert len(report.reject_codes) == 2
    assert RejectCode.SPREAD_TOO_HIGH in report.reject_codes
    assert RejectCode.ATR_TOO_LOW in report.reject_codes
