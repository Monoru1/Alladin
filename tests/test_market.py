"""MarketUniverse dynamique, régimes, scanner, stratégies, routeur."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from alladin.brokers.mock import MockBroker
from alladin.challenge.models import ChallengeProfile
from alladin.core.enums import AssetCategory, MarketRegime, Side, SymbolTradeMode, Timeframe
from alladin.core.models import Bar, InstrumentSpec
from alladin.market.context import MacroEvent, NullContextProvider, StaticContextProvider
from alladin.market.regime import RegimeClassifier
from alladin.market.scanner import MarketScanner, session_label
from alladin.market.universe import MarketUniverse, classify_symbol
from alladin.strategies.base import StrategyContext
from alladin.strategies.registry import StrategyRegistry
from alladin.strategies.router import StrategyRouter
from tests.conftest import T0


def spec(base: str, quote: str, **kw: object) -> InstrumentSpec:
    data = dict(symbol=f"{base}{quote}", currency_base=base, currency_profit=quote, currency_margin=base, digits=5,
                point=1e-5, trade_tick_size=1e-5, trade_tick_value=1, trade_contract_size=1e5, volume_min=0.01,
                volume_max=10, volume_step=0.01)  # fmt: skip
    data.update(kw)
    return InstrumentSpec(**data)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("base", "quote", "cat"),
    [("EUR", "USD", AssetCategory.FOREX_MAJOR), ("USD", "JPY", AssetCategory.FOREX_MAJOR), ("GBP", "JPY", AssetCategory.FOREX_JPY),
     ("EUR", "GBP", AssetCategory.FOREX_MINOR), ("USD", "TRY", AssetCategory.FOREX_EXOTIC), ("XAU", "USD", AssetCategory.METAL),
     ("US500", "USD", AssetCategory.OTHER)],
)  # fmt: skip
def test_classification_uses_broker_currencies_not_names(base: str, quote: str, cat: AssetCategory) -> None:
    s = spec(base, quote)
    s.symbol += ".pro"  # suffixe broker : la classification ne doit pas en dépendre
    assert classify_symbol(s) is cat


def test_universe_is_discovered_from_the_broker_and_respects_profile(
    broker: MockBroker, profile: ChallengeProfile
) -> None:
    rep = MarketUniverse(broker, profile.universe).discover()
    names = {m.symbol for m in rep.members}
    assert rep.total_discovered == 16 and "EURUSD" in names and "GBPJPY" in names
    assert "XAUUSD" not in names and rep.excluded["XAUUSD"].startswith(
        "catégorie METAL"
    )  # métaux non autorisés par défaut
    assert rep.excluded["USDTRY"].startswith("catégorie FOREX_EXOTIC")
    assert sum(rep.by_category.values()) == len(rep.members)


def test_universe_follows_profile_and_broker_changes(profile: ChallengeProfile) -> None:
    profile.universe.allowed_categories = [AssetCategory.METAL, AssetCategory.FOREX_EXOTIC]
    profile.universe.include_symbols = ["EURUSD"]
    b = MockBroker(
        market={"XAUUSD": (2350, 35), "USDTRY": (32.5, 600), "EURUSD": (1.085, 12), "EURGBP": (0.85, 14)}
    )
    names = {m.symbol for m in MarketUniverse(b, profile.universe).discover().members}
    assert names == {
        "XAUUSD",
        "USDTRY",
        "EURUSD",
    }  # un autre broker => un autre univers, sans toucher au code


def test_non_tradable_and_broken_specs_are_excluded(
    broker: MockBroker, profile: ChallengeProfile, monkeypatch: pytest.MonkeyPatch
) -> None:
    specs = broker.list_symbols()
    specs[0].trade_mode = SymbolTradeMode.CLOSE_ONLY
    specs[1].volume_step = 0
    monkeypatch.setattr(broker, "list_symbols", lambda: specs)
    rep = MarketUniverse(broker, profile.universe).discover()
    assert "non négociable" in rep.excluded[specs[0].symbol] and "incomplète" in rep.excluded[specs[1].symbol]


def bars(closes: list[float], wick: float = 0.0004) -> list[Bar]:
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    out, prev = [], closes[0]
    for i, c in enumerate(closes):
        out.append(
            Bar(
                time=t0 + timedelta(hours=i),
                open=prev,
                high=max(prev, c) + wick,
                low=min(prev, c) - wick,
                close=c,
                tick_volume=100,
            )
        )
        prev = c
    return out


def noise(n: int, amp: float = 0.0008) -> list[float]:
    return [1.1 + amp * math.sin(i * 0.9) * math.cos(i * 0.37) for i in range(n)]


def test_regime_trend() -> None:
    closes = [1.0 + i * 0.0006 + 0.0002 * math.sin(i) for i in range(200)]
    a = RegimeClassifier().classify(bars(closes))
    assert a.regime is MarketRegime.TREND and a.metrics["er20"] > 0.35


def test_regime_range() -> None:
    a = RegimeClassifier().classify(bars(noise(200)))
    assert a.regime in (MarketRegime.RANGE, MarketRegime.LOW_VOLATILITY)


def test_regime_breakout_on_expansion_bar() -> None:
    closes = noise(199) + [1.1 + 0.0008 + 0.006]
    a = RegimeClassifier().classify(bars(closes))
    assert a.regime is MarketRegime.BREAKOUT


def test_regime_news_event_overrides_and_unknown_when_no_data() -> None:
    ctx = StaticContextProvider([MacroEvent(time=T0, currency="USD", title="NFP")]).get_context(
        ("EUR", "USD"), T0
    )
    assert RegimeClassifier().classify(bars(noise(200)), ctx).regime is MarketRegime.NEWS_EVENT
    assert RegimeClassifier().classify(bars(noise(10))).regime is MarketRegime.UNKNOWN
    assert not NullContextProvider().get_context(("EUR",), T0).news_blackout


def test_scanner_produces_shortlist_without_sending_orders(
    broker: MockBroker, profile: ChallengeProfile
) -> None:
    rep = MarketScanner(broker, MarketUniverse(broker, profile.universe), profile.universe).scan()
    assert rep.universe_size == 14 and rep.analysed == 14
    assert 0 < len(rep.candidates) <= profile.universe.shortlist_size
    scores = [c.score for c in rep.candidates]
    assert scores == sorted(scores, reverse=True) and all(0 <= s <= 1 for s in scores)
    assert all(c.regime not in (MarketRegime.UNKNOWN, MarketRegime.NEWS_EVENT) for c in rep.candidates)
    assert broker.sent_orders == [] and broker.positions() == []
    assert set(rep.rejected) >= {"XAUUSD", "USDTRY"}  # exclus par le profil, avec raison


def test_scanner_rejects_wide_spreads_and_reports_why(profile: ChallengeProfile) -> None:
    b = MockBroker(market={"EURUSD": (1.085, 12), "GBPUSD": (1.27, 4000)}, start=T0)  # spread absurde
    rep = MarketScanner(b, MarketUniverse(b, profile.universe), profile.universe).scan()
    assert "GBPUSD" not in {c.symbol for c in rep.candidates}
    assert any("spread/ATR" in r or "régime" in r for r in rep.rejected["GBPUSD"])


def test_scanner_isolates_a_failing_symbol(
    broker: MockBroker, profile: ChallengeProfile, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = broker.bars

    def flaky(sym: str, tf: Timeframe, n: int) -> list[Bar]:
        if sym == "EURUSD":
            raise RuntimeError("feed cassé")
        return real(sym, tf, n)

    monkeypatch.setattr(broker, "bars", flaky)
    rep = MarketScanner(broker, MarketUniverse(broker, profile.universe), profile.universe).scan()
    assert "feed cassé" in rep.rejected["EURUSD"][0] and rep.analysed == 13


def test_session_labels() -> None:
    assert session_label(datetime(2026, 1, 5, 7, 30, tzinfo=UTC)) == "TOKYO+LONDON"
    assert session_label(datetime(2026, 1, 5, 14, tzinfo=UTC)) == "LONDON+NEWYORK"
    assert session_label(datetime(2026, 1, 5, 22, tzinfo=UTC)) == "OFF_HOURS"


# ---------------------------------------------------------------------------- stratégies


def test_registry_loads_versioned_strategies_from_config(settings) -> None:  # type: ignore[no-untyped-def]
    reg = StrategyRegistry.from_config(settings.strategies_dir)
    assert {s.id for s in reg.enabled()} == {"TREND-01", "BREAKOUT-01", "RANGE-01"}
    assert all(s.version == "1.0.0" for s in reg.enabled())
    cat = {c["id"]: c for c in reg.catalogue()}
    assert (
        not cat["NEWS-01"]["enabled"] and "planifiée" in cat["NEWS-01"]["note"]
    )  # planifié, pas encore implémenté


def test_registry_enable_disable_and_version_pinning(settings) -> None:  # type: ignore[no-untyped-def]
    from alladin.strategies.registry import StrategyConfig

    reg = StrategyRegistry.from_config(settings.strategies_dir)
    reg.activate(StrategyConfig(id="TREND-01", version="1.0.0", enabled=False))
    assert reg.get("TREND-01") is None
    reg.activate(
        StrategyConfig(id="TREND-01", version="9.9.9", enabled=True)
    )  # version inexistante : refusée, pas devinée
    assert reg.get("TREND-01") is None and "9.9.9" in reg.unavailable["TREND-01"]


def test_router_selects_by_regime(broker: MockBroker, profile: ChallengeProfile, settings) -> None:  # type: ignore[no-untyped-def]
    rep = MarketScanner(broker, MarketUniverse(broker, profile.universe), profile.universe).scan()
    router = StrategyRouter(StrategyRegistry.from_config(settings.strategies_dir))
    cand = rep.candidates[0]
    for regime, expected in ((MarketRegime.TREND, ["TREND-01"]), (MarketRegime.BREAKOUT, ["BREAKOUT-01"]),
                             (MarketRegime.RANGE, ["RANGE-01"]), (MarketRegime.NEWS_EVENT, [])):  # fmt: skip
        decision, strategies = router.route(cand.model_copy(update={"regime": regime}))
        assert decision.selected == expected == [s.id for s in strategies]
    decision, _ = router.route(cand.model_copy(update={"regime": MarketRegime.NEWS_EVENT}))
    assert decision.skipped  # les refus sont expliqués (audit NO TRADE)


def test_router_ranks_by_measured_performance(
    broker: MockBroker, profile: ChallengeProfile, settings
) -> None:  # type: ignore[no-untyped-def]
    reg = StrategyRegistry.from_config(settings.strategies_dir)
    reg.get("BREAKOUT-01").compatible_regimes = frozenset({MarketRegime.TREND, MarketRegime.BREAKOUT})  # type: ignore[union-attr]

    class Perf:
        def expectancy_r(self, sid: str, ver: str, regime: MarketRegime) -> float | None:
            return {"TREND-01": -0.2, "BREAKOUT-01": 0.6}.get(sid)

    cand = (
        MarketScanner(broker, MarketUniverse(broker, profile.universe), profile.universe).scan().candidates[0]
    )
    decision, _ = StrategyRouter(reg, Perf()).route(cand.model_copy(update={"regime": MarketRegime.TREND}))
    assert decision.selected == ["BREAKOUT-01", "TREND-01"]


def test_trend_strategy_signal_carries_strategy_id_and_version(
    broker: MockBroker, profile: ChallengeProfile, settings
) -> None:  # type: ignore[no-untyped-def]
    from alladin.strategies.trend import Trend01

    cand = (
        MarketScanner(broker, MarketUniverse(broker, profile.universe), profile.universe).scan().candidates[0]
    )
    atr, px = 0.0010, cand.tick.ask  # type: ignore[union-attr]
    metrics = {
        **cand.metrics,
        "ema20": px - 0.0005,
        "ema50": px - 0.004,
        "close": px - 0.0004,
        "atr": atr,
        "er20": 0.5,
        "rsi14": 55,
    }
    c = cand.model_copy(
        update={"metrics": metrics, "regime": MarketRegime.TREND, "tf_trend": {"H4": 1, "H1": 1}}
    )
    ctx = StrategyContext(run_id="RUN-001", now=T0, candidate=c)
    strat = Trend01()
    sig = strat.evaluate(ctx)
    assert sig and sig.side is Side.BUY and sig.stop_loss < px < (sig.take_profit or 0)
    intent = strat.to_intent(sig, ctx)
    assert (intent.strategy_id, intent.strategy_version, intent.market_regime) == (
        "TREND-01",
        "1.0.0",
        MarketRegime.TREND,
    )
    assert intent.requested_risk_pct_of_working_capital <= 6  # jamais 8 % par défaut
    # la timeframe supérieure contredit => pas de signal
    assert (
        strat.evaluate(ctx.model_copy(update={"candidate": c.model_copy(update={"tf_trend": {"H4": -1}})}))
        is None
    )
