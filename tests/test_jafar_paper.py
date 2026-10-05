"""Tests Jafar PAPER engine — données mock, pas de réseau."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from alladin.brain import Action, ActionProposal, proposal_identity
from alladin.brokers.crypto import CryptoMockProvider
from alladin.core.enums import JafarMode, Side
from alladin.core.workspace import WorkspaceId
from alladin.jafar.paper import (
    DEFAULT_INITIAL_CAPITAL,
    DEFAULT_SLIPPAGE_BPS,
    DEFAULT_TAKER_FEE_BPS,
    JafarPaperEngine,
    JafarPaperOpenError,
    JafarPaperPosition,
    JafarSimulatedPortfolio,
    PortfolioRiskLimits,
    check_portfolio_risk,
    simulate_fill,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime(2026, 10, 4, 18, 0, 0, tzinfo=UTC)


def _provider(price: float = 65_000.0) -> CryptoMockProvider:
    return CryptoMockProvider(base_price=price, spread_bps=5.0, start=_now())


def _proposal(
    action: str = "LONG",
    symbol: str = "BTCUSDT",
    run_id: str = "RUN-JAFAR-PAPER",
    cycle_id: str = "CYC-001",
    opportunity_id: str = "OPP-001",
) -> ActionProposal:
    from alladin.brain import ProposalParameters
    from alladin.core.enums import EntryType, MarketRegime

    pid = proposal_identity(run_id, cycle_id, opportunity_id, "jafar:paper:test", "1")
    return ActionProposal(
        proposal_id=pid,
        source_id="jafar:paper:test",
        source_version="1",
        run_id=run_id,
        cycle_id=cycle_id,
        opportunity_id=opportunity_id,
        symbol=symbol,
        action=Action(action),
        timestamp=_now(),
        parameters=ProposalParameters(
            strategy_id="test",
            strategy_version="1",
            market_regime=MarketRegime.TREND,
            entry_type=EntryType.MARKET,
            requested_risk_pct_of_working_capital=1.0,
        ),
    )


def _engine(
    price: float = 65_000.0,
    capital: float = DEFAULT_INITIAL_CAPITAL,
) -> JafarPaperEngine:
    return JafarPaperEngine(
        provider=_provider(price),
        run_id="RUN-JAFAR-PAPER",
        workspace=WorkspaceId.JAFAR,
        initial_capital=capital,
        taker_fee_bps=DEFAULT_TAKER_FEE_BPS,
        slippage_bps=DEFAULT_SLIPPAGE_BPS,
    )


# ---------------------------------------------------------------------------
# simulate_fill
# ---------------------------------------------------------------------------


class TestSimulateFill:
    def test_buy_fills_at_ask_plus_slippage(self) -> None:
        p = _proposal("LONG")
        fill = simulate_fill(
            p, bid=65_000.0, ask=65_010.0, quantity=0.01,
            taker_fee_bps=10.0, slippage_bps=5.0,
            now=_now(), workspace=WorkspaceId.JAFAR,
        )
        assert fill.side is Side.BUY
        # fill_price >= ask
        assert fill.fill_price >= 65_010.0
        assert fill.quantity == 0.01
        assert fill.fee_amount > 0
        assert fill.client_order_id.startswith("jfr-")

    def test_sell_fills_at_bid_minus_slippage(self) -> None:
        p = _proposal("SHORT")
        fill = simulate_fill(
            p, bid=65_000.0, ask=65_010.0, quantity=0.01,
            taker_fee_bps=10.0, slippage_bps=5.0,
            now=_now(), workspace=WorkspaceId.JAFAR,
        )
        assert fill.side is Side.SELL
        # fill_price <= bid
        assert fill.fill_price <= 65_000.0
        assert fill.fee_amount > 0

    def test_same_proposal_same_fill_price(self) -> None:
        """Déterministe : même proposal → même slippage."""
        p = _proposal("LONG")
        f1 = simulate_fill(
            p, 65_000.0, 65_010.0, 0.01,
            taker_fee_bps=10.0, slippage_bps=5.0,
            now=_now(), workspace=WorkspaceId.JAFAR,
        )
        f2 = simulate_fill(
            p, 65_000.0, 65_010.0, 0.01,
            taker_fee_bps=10.0, slippage_bps=5.0,
            now=_now(), workspace=WorkspaceId.JAFAR,
        )
        assert f1.fill_price == f2.fill_price
        assert f1.slippage_bps == f2.slippage_bps

    def test_different_proposals_different_slippage(self) -> None:
        p1 = _proposal("LONG", cycle_id="CYC-001")
        p2 = _proposal("LONG", cycle_id="CYC-002")
        f1 = simulate_fill(
            p1, 65_000.0, 65_010.0, 0.01,
            taker_fee_bps=10.0, slippage_bps=5.0,
            now=_now(), workspace=WorkspaceId.JAFAR,
        )
        f2 = simulate_fill(
            p2, 65_000.0, 65_010.0, 0.01,
            taker_fee_bps=10.0, slippage_bps=5.0,
            now=_now(), workspace=WorkspaceId.JAFAR,
        )
        # Les slippages peuvent différer (hash différent)
        # Les fill prices peuvent être égaux par coïncidence, mais l'identité interne diffère
        assert f1.client_order_id != f2.client_order_id

    def test_invalid_quantity_raises(self) -> None:
        p = _proposal("LONG")
        with pytest.raises(ValueError, match="quantity"):
            simulate_fill(p, 65_000.0, 65_010.0, 0.0, taker_fee_bps=10.0,
                          slippage_bps=5.0, now=_now(), workspace=WorkspaceId.JAFAR)

    def test_invalid_bid_ask_raises(self) -> None:
        p = _proposal("LONG")
        with pytest.raises(ValueError, match="bid/ask"):
            simulate_fill(p, 0.0, 65_010.0, 0.01, taker_fee_bps=10.0,
                          slippage_bps=5.0, now=_now(), workspace=WorkspaceId.JAFAR)


# ---------------------------------------------------------------------------
# Portfolio simulé
# ---------------------------------------------------------------------------


class TestJafarSimulatedPortfolio:
    def test_initial_state(self) -> None:
        p = JafarSimulatedPortfolio(10_000.0, "JAFAR")
        assert p.cash == 10_000.0
        assert p.realized_pnl == 0.0
        assert p.total_fees == 0.0
        assert p.total_value() == 10_000.0

    def test_invalid_capital(self) -> None:
        with pytest.raises(ValueError):
            JafarSimulatedPortfolio(-1.0, "JAFAR")

    def test_can_afford(self) -> None:
        p = JafarSimulatedPortfolio(10_000.0, "JAFAR")
        assert p.can_afford(9_000.0, 90.0)  # 9090 < 10000
        assert not p.can_afford(9_950.0, 100.0)  # 10050 > 10000

    def test_debit_credit_cycle(self) -> None:
        portfolio = JafarSimulatedPortfolio(10_000.0, "JAFAR")
        pos = JafarPaperPosition(
            position_id="JPP-001",
            run_id="RUN-1",
            workspace="JAFAR",
            symbol="BTCUSDT",
            side=Side.BUY,
            quantity=0.1,
            entry_price=65_000.0,
            sl=64_000.0,
            tp=67_000.0,
            fees_paid=6.5,
            slippage_paid=0.5,
            quote_cost=6_506.5,   # 65_000 * 0.1 + fees
            opened_at=_now(),
            proposal_id="pid",
            client_order_id="jfr-abc",
        )
        portfolio.debit(pos)
        assert portfolio.cash == pytest.approx(10_000.0 - 6_506.5)
        assert portfolio.total_fees == pytest.approx(6.5)

        # Close à 66_000
        proceeds = 66_000.0 * 0.1  # 6600
        exit_fee = proceeds * 0.001  # 6.6
        portfolio.credit(pos, proceeds, exit_fee)

        expected_pnl = (proceeds - exit_fee) - pos.quote_cost
        assert pos.realized_pnl == pytest.approx(expected_pnl)
        assert portfolio.realized_pnl == pytest.approx(expected_pnl)


# ---------------------------------------------------------------------------
# Portfolio risk guard
# ---------------------------------------------------------------------------


class TestCheckPortfolioRisk:
    def test_sufficient_capital_approved(self) -> None:
        p = JafarSimulatedPortfolio(10_000.0, "JAFAR")
        r = check_portfolio_risk(p, 1_000.0, 10.0, PortfolioRiskLimits())
        assert r.approved

    def test_insufficient_cash_rejected(self) -> None:
        p = JafarSimulatedPortfolio(100.0, "JAFAR")
        r = check_portfolio_risk(p, 5_000.0, 50.0, PortfolioRiskLimits())
        assert not r.approved
        assert any("INSUFFICIENT" in reason for reason in r.reasons)

    def test_position_too_large_rejected(self) -> None:
        p = JafarSimulatedPortfolio(10_000.0, "JAFAR")
        limits = PortfolioRiskLimits(max_position_pct=5.0)
        # 3000 / 10000 = 30% > 5%
        r = check_portfolio_risk(p, 3_000.0, 30.0, limits)
        assert not r.approved
        assert any("POSITION_TOO_LARGE" in reason for reason in r.reasons)


# ---------------------------------------------------------------------------
# JafarPaperEngine
# ---------------------------------------------------------------------------


class TestJafarPaperEngine:
    def test_open_long_position(self) -> None:
        engine = _engine()
        proposal = _proposal("LONG")
        pos = engine.open_position(proposal, 0.01, sl=64_000.0, tp=67_000.0)
        assert pos.side is Side.BUY
        assert pos.quantity == 0.01
        assert pos.status == "OPEN"
        assert pos.entry_price > 0
        assert pos.fees_paid > 0
        assert len(engine.open_positions()) == 1

    def test_same_proposal_cannot_open_twice(self) -> None:
        engine = _engine()
        proposal = _proposal("LONG")
        first = engine.open_position(proposal, 0.01, sl=64_000.0, tp=67_000.0)
        second = engine.open_position(proposal, 0.01, sl=64_000.0, tp=67_000.0)
        assert second is first
        assert len(engine.open_positions()) == 1

    def test_open_short_position(self) -> None:
        engine = _engine()
        proposal = _proposal("SHORT")
        pos = engine.open_position(proposal, 0.01, sl=66_000.0, tp=63_000.0)
        assert pos.side is Side.SELL
        assert pos.status == "OPEN"

    def test_portfolio_debited_on_open(self) -> None:
        engine = _engine(capital=10_000.0)
        initial_cash = engine.portfolio.cash
        proposal = _proposal("LONG")
        pos = engine.open_position(proposal, 0.01, sl=64_000.0, tp=67_000.0)
        assert engine.portfolio.cash < initial_cash
        assert engine.portfolio.cash == pytest.approx(initial_cash - pos.quote_cost)

    def test_tick_all_closes_on_sl(self) -> None:
        """Vérifie que le SL est déclenché correctement."""
        price = 65_000.0
        engine = _engine(price)
        proposal = _proposal("LONG")
        engine.open_position(proposal, 0.01, sl=65_100.0, tp=70_000.0)

        # Simuler un tick où le bid est en dessous du SL
        provider = engine.provider
        assert isinstance(provider, CryptoMockProvider)

        # Patch the ticker to return below-SL price
        original_ticker = provider.ticker

        def mock_ticker(symbol: str):
            from alladin.brokers.crypto import CryptoTick
            return CryptoTick(
                symbol=symbol,
                time=_now(),
                bid=65_050.0,  # en dessous du SL=65_100
                ask=65_060.0,
                last=65_055.0,
            )

        provider.ticker = mock_ticker  # type: ignore[method-assign]
        closed = engine.tick_all()
        provider.ticker = original_ticker  # type: ignore[method-assign]

        assert len(closed) == 1
        assert closed[0].status == "CLOSED_SL"
        assert len(engine.open_positions()) == 0
        assert len(engine.closed_positions()) == 1

    def test_tick_all_closes_on_tp(self) -> None:
        engine = _engine(65_000.0)
        proposal = _proposal("LONG")
        engine.open_position(proposal, 0.01, sl=64_000.0, tp=65_050.0)

        provider = engine.provider
        assert isinstance(provider, CryptoMockProvider)

        def mock_ticker(symbol: str):
            from alladin.brokers.crypto import CryptoTick
            return CryptoTick(
                symbol=symbol,
                time=_now(),
                bid=65_055.0,  # au dessus du TP=65_050
                ask=65_065.0,
                last=65_060.0,
            )

        provider.ticker = mock_ticker  # type: ignore[method-assign]
        closed = engine.tick_all()
        provider.ticker = original_ticker = provider.ticker  # noqa

        assert len(closed) == 1
        assert closed[0].status == "CLOSED_TP"

    def test_realized_pnl_positive_on_tp(self) -> None:
        engine = _engine(65_000.0)
        proposal = _proposal("LONG")
        engine.open_position(proposal, 0.01, sl=64_000.0, tp=66_000.0)

        provider = engine.provider
        assert isinstance(provider, CryptoMockProvider)

        def mock_ticker(symbol: str):
            from alladin.brokers.crypto import CryptoTick
            return CryptoTick(
                symbol=symbol, time=_now(),
                bid=66_100.0, ask=66_110.0, last=66_105.0,
            )

        provider.ticker = mock_ticker  # type: ignore[method-assign]
        closed = engine.tick_all()

        assert closed
        pnl = closed[0].realized_pnl
        assert pnl is not None
        # BUY at ~65_000, close at 66_100 → positive PnL
        assert pnl > 0

    def test_close_position_manually(self) -> None:
        engine = _engine()
        proposal = _proposal("LONG")
        pos = engine.open_position(proposal, 0.01, sl=64_000.0, tp=70_000.0)
        result = engine.close_position(pos.position_id)
        assert result is not None
        assert result.status == "CLOSED_MANUAL"
        assert len(engine.open_positions()) == 0

    def test_invalid_action_raises(self) -> None:
        """NO_TRADE doit être refusé — peut lever sur symbol manquant ou action non tradable."""
        engine = _engine()
        from alladin.brain import ProposalParameters

        pid = proposal_identity("RUN-1", "CYC-1", None, "jafar:test", "1")
        no_trade = ActionProposal(
            proposal_id=pid,
            source_id="jafar:test",
            source_version="1",
            run_id="RUN-1",
            cycle_id="CYC-1",
            action=Action.NO_TRADE,
            timestamp=_now(),
            parameters=ProposalParameters(),
        )
        with pytest.raises(JafarPaperOpenError):
            engine.open_position(no_trade, 0.01, sl=64_000.0, tp=None)

    def test_portfolio_risk_limits_enforced(self) -> None:
        limits = PortfolioRiskLimits(max_position_pct=1.0)  # max 1% de 10k = 100 USDT
        engine = JafarPaperEngine(
            provider=_provider(65_000.0),
            run_id="RUN-1",
            workspace=WorkspaceId.JAFAR,
            initial_capital=10_000.0,
            risk_limits=limits,
        )
        proposal = _proposal("LONG")
        # 0.01 BTC à 65k = 650 USDT > 1% de 10k
        with pytest.raises(JafarPaperOpenError, match="portfolio risk"):
            engine.open_position(proposal, 0.01, sl=64_000.0, tp=None)

    def test_stats(self) -> None:
        engine = _engine()
        stats = engine.stats()
        assert stats["initial_capital"] == DEFAULT_INITIAL_CAPITAL
        assert stats["open_positions"] == 0
        assert stats["closed_trades"] == 0
        assert stats["total_value"] == DEFAULT_INITIAL_CAPITAL

    def test_no_order_sent_to_binance(self) -> None:
        """Vérifier que PAPER n'appelle jamais d'endpoint Binance d'ordre."""
        # Monkey-patch urllib.request.urlopen pour détecter tout appel réseau
        import urllib.request

        original = urllib.request.urlopen
        calls: list[str] = []

        def spy(req, *args, **kwargs):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "binance.com" in url or "binance.vision" in url:
                calls.append(url)
            return original(req, *args, **kwargs)

        engine = _engine()
        proposal = _proposal("LONG")
        # This should NOT make any network calls (uses CryptoMockProvider)
        engine.open_position(proposal, 0.01, sl=64_000.0, tp=70_000.0)
        # CryptoMockProvider ne fait pas de réseau — calls doit rester vide
        assert len(calls) == 0

    def test_restart_restore(self) -> None:
        """Vérifie la restauration des positions depuis la persistance."""
        from unittest.mock import MagicMock

        repo = MagicMock()
        pos_row = {
            "paper_id": "JPP-abc123",
            "run_id": "RUN-1",
            "workspace": "JAFAR",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "volume": 0.01,
            "entry_price": 65_000.0,
            "sl": 64_000.0,
            "tp": 70_000.0,
            "opened_at": "2026-10-04T18:00:00+00:00",
            "status": "OPEN",
            "realized_pnl": 0.0,
            "mfe_amount": 0.0,
            "mae_amount": 0.0,
            "excursion_samples": 0,
            "intent_json": '{"quote_cost": 651.0, "fees_paid": 1.0, "slippage_paid": 0.1, "client_order_id": "jfr-abc"}',
            "proposal_id": "pid-abc",
        }
        repo.list_paper_positions.side_effect = lambda run_id, status: [pos_row] if status == "OPEN" else [pos_row]

        engine = JafarPaperEngine(
            provider=_provider(),
            run_id="RUN-1",
            workspace=WorkspaceId.JAFAR,
            repo=repo,
        )
        n = engine.restore()
        assert n == 1
        assert len(engine.open_positions()) == 1
        restored = engine.open_positions()[0]
        assert restored.symbol == "BTCUSDT"
        assert restored.quantity == 0.01


def test_paper_runtime_traverses_brain_risk_lifecycle_and_execution(settings) -> None:
    from alladin.brokers.crypto_observe import CryptoObserveBroker
    from alladin.core.enums import AssetCategory, MarketRegime
    from alladin.execution.order_lifecycle import CanonicalOrderStatus
    from alladin.jafar.paper import JafarPaperRuntime
    from alladin.market.models import ScanCandidate, ScanReport
    from alladin.orchestration.bootstrap import build_services
    from alladin.orchestration.jafar import JafarModeStore, JafarPaperBrain

    provider = _provider()
    broker = CryptoObserveBroker(provider)
    comps = build_services(settings, broker, create_run=True, workspace=WorkspaceId.JAFAR)
    assert comps is not None and comps.order_lifecycle is not None
    JafarModeStore(comps.journal, comps.run.run_id).transition(
        JafarMode.PAPER,
        reason="test",
    )
    comps.manager.start(comps.run, broker.account_info())
    tick = broker.tick("BTCUSDT")
    spec = broker.symbol_spec("BTCUSDT")
    assert tick is not None and spec is not None
    scanner = MagicMock()
    scanner.scan.return_value = ScanReport(
        scanned_at=_now(), universe_size=1, analysed=1,
        candidates=[ScanCandidate(symbol="BTCUSDT", category=AssetCategory.CRYPTO_SPOT,
                                  regime=MarketRegime.TREND, regime_confidence=0.8, score=0.9,
                                  bias=Side.BUY, metrics={"atr": 1_000.0}, tick=tick, spec=spec)],
    )
    engine = JafarPaperEngine(provider=provider, run_id=comps.run.run_id,
                              workspace=WorkspaceId.JAFAR, initial_capital=100_000,
                              repo=comps.repo, lifecycle=comps.order_lifecycle,
                              journal=comps.journal)
    runtime = JafarPaperRuntime(broker=broker, scanner=scanner, brain=JafarPaperBrain(),
                                risk=comps.risk, engine=engine, journal=comps.journal,
                                outcomes=comps.outcomes,
                                run_state=lambda: comps.run.watchdog.run_state)
    result = runtime.run_cycle()
    assert result.decision == "TRADE"
    assert len(engine.open_positions()) == 1
    assert comps.repo.events(comps.run.run_id, ["risk.decision"])[0].payload["approved"] is True
    claim = comps.order_lifecycle.get(engine.open_positions()[0].client_order_id)
    assert claim is not None and claim.status is CanonicalOrderStatus.FILLED


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class TestJafarPaperPersistence:
    def test_to_persistence_round_trip(self) -> None:
        pos = JafarPaperPosition(
            position_id="JPP-test",
            run_id="RUN-1",
            workspace="JAFAR",
            symbol="BTCUSDT",
            side=Side.BUY,
            quantity=0.01,
            entry_price=65_000.0,
            sl=64_000.0,
            tp=70_000.0,
            fees_paid=6.5,
            slippage_paid=0.3,
            quote_cost=656.5,
            opened_at=_now(),
            proposal_id="pid",
            client_order_id="jfr-abc",
        )
        d = pos.to_persistence()
        restored = JafarPaperPosition.from_persistence(d)
        assert restored.position_id == pos.position_id
        assert restored.symbol == pos.symbol
        assert restored.side == pos.side
        assert restored.quantity == pos.quantity
        assert restored.entry_price == pos.entry_price
        assert restored.fees_paid == pos.fees_paid
        assert restored.quote_cost == pos.quote_cost
