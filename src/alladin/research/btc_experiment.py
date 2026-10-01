"""BTC Three-Way Experiment : 3 hypotheses BTC simultanees en PAPER.

Exactement 3 experiments :
- BTC-EXP-A : TREND (multi-timeframe)
- BTC-EXP-B : BREAKOUT (volatility/compression)
- BTC-EXP-C : MEAN_REVERSION (range, seulement si regime le justifie)

Si le marche ne qualifie PAS une strategie, l'experience est enregistree
comme NO_ENTRY / REJECTED avec la raison.

JAMAIS de trade force. 3 EXPERIMENTS, pas 3 trades irrationnels.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from alladin.brokers.crypto import CryptoDataProvider, CryptoTick
from alladin.core.enums import MarketRegime, Side, Timeframe
from alladin.core.models import Bar
from alladin.market.regime import RegimeClassifier

log = logging.getLogger(__name__)

SYMBOL = "BTCUSDT"
NOTIONAL_CAPITAL = 10000.0  # capital notionnel de comparaison (USDT)
FEE_BPS = 10.0  # 10 bps = 0.1% par trade (maker+taker moyen)


class ExperimentStatus:
    PENDING = "PENDING"
    QUALIFIED = "QUALIFIED"
    NO_ENTRY = "NO_ENTRY"
    REJECTED = "REJECTED"
    OPEN = "OPEN"
    CLOSED_SL = "CLOSED_SL"
    CLOSED_TP = "CLOSED_TP"
    CLOSED_MANUAL = "CLOSED_MANUAL"
    EXPIRED = "EXPIRED"


@dataclass
class BTCExperimentPosition:
    """Position paper d'une experience BTC."""

    experiment_id: str
    side: Side
    entry_price: float
    stop_loss: float
    take_profit: float | None
    size_btc: float  # taille en BTC
    opened_at: datetime
    exit_price: float | None = None
    closed_at: datetime | None = None
    status: str = ExperimentStatus.OPEN
    pnl_usdt: float = 0.0
    pnl_r: float = 0.0
    mfe_price: float | None = None
    mae_price: float | None = None
    mfe_r: float = 0.0
    mae_r: float = 0.0

    @property
    def is_open(self) -> bool:
        return self.status == ExperimentStatus.OPEN


@dataclass
class BTCExperiment:
    """Une des trois experiences BTC."""

    experiment_id: str
    name: str  # BTC-EXP-A, BTC-EXP-B, BTC-EXP-C
    hypothesis: str  # TREND, BREAKOUT, MEAN_REVERSION
    strategy_id: str
    strategy_version: str = "1.0.0"

    # Snapshot au moment de l'evaluation
    evaluated_at: datetime | None = None
    regime: MarketRegime = MarketRegime.UNKNOWN
    regime_confidence: float = 0.0

    # Decision
    status: str = ExperimentStatus.PENDING
    rejection_reason: str = ""
    signal_details: dict[str, Any] = field(default_factory=dict)

    # Position (si qualifiee)
    position: BTCExperimentPosition | None = None

    # Cost model
    notional_capital: float = NOTIONAL_CAPITAL
    fee_bps: float = FEE_BPS

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "name": self.name,
            "hypothesis": self.hypothesis,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "evaluated_at": self.evaluated_at.isoformat() if self.evaluated_at else None,
            "regime": self.regime.value,
            "regime_confidence": round(self.regime_confidence, 3),
            "status": self.status,
            "rejection_reason": self.rejection_reason,
            "signal_details": self.signal_details,
            "position": {
                "side": self.position.side.value,
                "entry_price": self.position.entry_price,
                "stop_loss": self.position.stop_loss,
                "take_profit": self.position.take_profit,
                "size_btc": self.position.size_btc,
                "opened_at": self.position.opened_at.isoformat(),
                "exit_price": self.position.exit_price,
                "closed_at": self.position.closed_at.isoformat() if self.position.closed_at else None,
                "status": self.position.status,
                "pnl_usdt": round(self.position.pnl_usdt, 2),
                "pnl_r": round(self.position.pnl_r, 4),
                "mfe_r": round(self.position.mfe_r, 4),
                "mae_r": round(self.position.mae_r, 4),
            } if self.position else None,
            "notional_capital": self.notional_capital,
            "fee_bps": self.fee_bps,
        }


def _create_three_experiments() -> list[BTCExperiment]:
    """Cree exactement 3 experiments."""
    return [
        BTCExperiment(
            experiment_id=f"BTC-EXP-A-{uuid4().hex[:8]}",
            name="BTC-EXP-A",
            hypothesis="TREND",
            strategy_id="TREND-01",
        ),
        BTCExperiment(
            experiment_id=f"BTC-EXP-B-{uuid4().hex[:8]}",
            name="BTC-EXP-B",
            hypothesis="BREAKOUT",
            strategy_id="BREAKOUT-01",
        ),
        BTCExperiment(
            experiment_id=f"BTC-EXP-C-{uuid4().hex[:8]}",
            name="BTC-EXP-C",
            hypothesis="MEAN_REVERSION",
            strategy_id="RANGE-01",
        ),
    ]


class BTCThreeWayEngine:
    """Gere les 3 experiences BTC simultanees.

    Usage :
        engine = BTCThreeWayEngine(provider)
        experiments = engine.evaluate()  # analyse et decide
        engine.tick_all()  # update positions ouvertes
    """

    def __init__(
        self,
        provider: CryptoDataProvider,
        classifier: RegimeClassifier | None = None,
        *,
        notional: float = NOTIONAL_CAPITAL,
        fee_bps: float = FEE_BPS,
        risk_pct: float = 2.0,  # % du notional par trade
    ) -> None:
        self.provider = provider
        self.classifier = classifier or RegimeClassifier()
        self.notional = notional
        self.fee_bps = fee_bps
        self.risk_pct = risk_pct
        self.experiments: list[BTCExperiment] = []
        self._evaluated = False

    def evaluate(self) -> list[BTCExperiment]:
        """Evalue les 3 hypotheses sur le snapshot actuel."""
        self.experiments = _create_three_experiments()
        self._evaluated = True

        # Fetch data
        bars_h1 = self.provider.klines(SYMBOL, Timeframe.H1, 300)
        bars_m15 = self.provider.klines(SYMBOL, Timeframe.M15, 300)
        bars_m5 = self.provider.klines(SYMBOL, Timeframe.M5, 300)
        tick = self.provider.ticker(SYMBOL)

        if not bars_h1 or not tick:
            for exp in self.experiments:
                exp.status = ExperimentStatus.REJECTED
                exp.rejection_reason = "NO_DATA: insufficient market data"
                exp.evaluated_at = self.provider.now()
            return self.experiments

        # Classify regime on H1
        assessment = self.classifier.classify(bars_h1)
        now = self.provider.now()

        for exp in self.experiments:
            exp.evaluated_at = now
            exp.regime = assessment.regime
            exp.regime_confidence = assessment.confidence
            exp.notional_capital = self.notional
            exp.fee_bps = self.fee_bps

            if exp.hypothesis == "TREND":
                self._evaluate_trend(exp, bars_h1, bars_m15, bars_m5, tick, assessment)
            elif exp.hypothesis == "BREAKOUT":
                self._evaluate_breakout(exp, bars_h1, bars_m5, tick, assessment)
            elif exp.hypothesis == "MEAN_REVERSION":
                self._evaluate_mean_reversion(exp, bars_h1, tick, assessment)

        return self.experiments

    def tick_all(self) -> list[BTCExperiment]:
        """Update toutes les positions ouvertes."""
        tick = self.provider.ticker(SYMBOL)
        if tick is None:
            return []

        closed: list[BTCExperiment] = []
        for exp in self.experiments:
            if exp.position and exp.position.is_open:
                self._update_position(exp.position, tick)
                exit_status = self._check_exit(exp.position, tick)
                if exit_status:
                    self._close_position(exp.position, tick, exit_status)
                    exp.status = exit_status
                    closed.append(exp)
        return closed

    def active_experiments(self) -> list[BTCExperiment]:
        return [e for e in self.experiments if e.position and e.position.is_open]

    def all_experiments(self) -> list[BTCExperiment]:
        return list(self.experiments)

    def summary(self) -> dict[str, Any]:
        return {
            "experiments": [e.to_dict() for e in self.experiments],
            "active": len(self.active_experiments()),
            "total": len(self.experiments),
        }

    # ------------------------------------------------------------------ evaluations

    def _evaluate_trend(
        self,
        exp: BTCExperiment,
        bars_h1: list[Bar],
        bars_m15: list[Bar],
        bars_m5: list[Bar],
        tick: CryptoTick,
        assessment: Any,
    ) -> None:
        """Multi-TF trend : H1 context, M15 structure, M5 trigger."""
        if assessment.regime != MarketRegime.TREND:
            exp.status = ExperimentStatus.NO_ENTRY
            exp.rejection_reason = f"REGIME_MISMATCH: {assessment.regime.value} != TREND"
            return

        metrics = assessment.metrics
        if not metrics:
            exp.status = ExperimentStatus.NO_ENTRY
            exp.rejection_reason = "NO_METRICS: regime classified without metrics"
            return

        # Direction from EMA alignment
        direction = 1 if metrics.get("ema20", 0) > metrics.get("ema50", 0) else -1
        atr = metrics.get("atr", 0)
        if atr <= 0:
            exp.status = ExperimentStatus.NO_ENTRY
            exp.rejection_reason = "ATR_ZERO"
            return

        side = Side.BUY if direction == 1 else Side.SELL
        entry = tick.ask if side == Side.BUY else tick.bid
        sl_dist = 1.5 * atr
        tp_dist = 2.5 * atr

        self._open_paper_position(exp, side, entry, sl_dist, tp_dist, tick)

    def _evaluate_breakout(
        self,
        exp: BTCExperiment,
        bars_h1: list[Bar],
        bars_m5: list[Bar],
        tick: CryptoTick,
        assessment: Any,
    ) -> None:
        """Breakout : compression -> breakout -> confirmation."""
        if assessment.regime != MarketRegime.BREAKOUT:
            exp.status = ExperimentStatus.NO_ENTRY
            exp.rejection_reason = f"REGIME_MISMATCH: {assessment.regime.value} != BREAKOUT"
            return

        metrics = assessment.metrics
        if not metrics:
            exp.status = ExperimentStatus.NO_ENTRY
            exp.rejection_reason = "NO_METRICS"
            return

        atr = metrics.get("atr", 0)
        if atr <= 0:
            exp.status = ExperimentStatus.NO_ENTRY
            exp.rejection_reason = "ATR_ZERO"
            return

        # Direction from breakout
        up = metrics.get("close", 0) > metrics.get("donchian_high", float("inf"))
        down = metrics.get("close", 0) < metrics.get("donchian_low", 0)
        if not up and not down:
            exp.status = ExperimentStatus.NO_ENTRY
            exp.rejection_reason = "NO_BREAKOUT: price within Donchian channel"
            return

        side = Side.BUY if up else Side.SELL
        entry = tick.ask if side == Side.BUY else tick.bid
        sl_dist = 1.2 * atr
        tp_dist = 2.4 * atr

        self._open_paper_position(exp, side, entry, sl_dist, tp_dist, tick)

    def _evaluate_mean_reversion(
        self,
        exp: BTCExperiment,
        bars_h1: list[Bar],
        tick: CryptoTick,
        assessment: Any,
    ) -> None:
        """Mean reversion : seulement en RANGE/LOW_VOLATILITY."""
        if assessment.regime not in (MarketRegime.RANGE, MarketRegime.LOW_VOLATILITY):
            exp.status = ExperimentStatus.NO_ENTRY
            exp.rejection_reason = f"REGIME_MISMATCH: {assessment.regime.value} not in RANGE/LOW_VOLATILITY"
            return

        metrics = assessment.metrics
        if not metrics:
            exp.status = ExperimentStatus.NO_ENTRY
            exp.rejection_reason = "NO_METRICS"
            return

        hi = metrics.get("donchian_high", 0)
        lo = metrics.get("donchian_low", 0)
        atr = metrics.get("atr", 0)
        close = metrics.get("close", 0)

        if atr <= 0 or hi <= lo:
            exp.status = ExperimentStatus.NO_ENTRY
            exp.rejection_reason = "INVALID_RANGE"
            return

        width = hi - lo
        pos = (close - lo) / width if width > 0 else 0.5

        if pos >= 0.85:
            side = Side.SELL
        elif pos <= 0.15:
            side = Side.BUY
        else:
            exp.status = ExperimentStatus.NO_ENTRY
            exp.rejection_reason = f"PRICE_MID_RANGE: position {pos:.0%} in channel (need <15% or >85%)"
            return

        entry = tick.ask if side == Side.BUY else tick.bid
        mid = (hi + lo) / 2
        sl = lo - 0.5 * atr if side == Side.BUY else hi + 0.5 * atr
        sl_dist = abs(entry - sl)
        tp_dist = abs(mid - entry)

        if tp_dist < 0.8 * sl_dist:
            exp.status = ExperimentStatus.NO_ENTRY
            exp.rejection_reason = f"POOR_RR: TP dist {tp_dist:.0f} < 0.8 * SL dist {sl_dist:.0f}"
            return

        self._open_paper_position(exp, side, entry, sl_dist, tp_dist, tick)

    # ------------------------------------------------------------------ position mgmt

    def _open_paper_position(
        self,
        exp: BTCExperiment,
        side: Side,
        entry: float,
        sl_dist: float,
        tp_dist: float,
        tick: CryptoTick,
    ) -> None:
        """Ouvre une position paper avec sizing base sur le risk_pct du notional."""
        risk_amount = self.notional * self.risk_pct / 100
        size_btc = risk_amount / sl_dist if sl_dist > 0 else 0
        if size_btc <= 0:
            exp.status = ExperimentStatus.REJECTED
            exp.rejection_reason = "SIZING_IMPOSSIBLE"
            return

        d = 1 if side == Side.BUY else -1
        exp.position = BTCExperimentPosition(
            experiment_id=exp.experiment_id,
            side=side,
            entry_price=entry,
            stop_loss=entry - d * sl_dist,
            take_profit=entry + d * tp_dist,
            size_btc=size_btc,
            opened_at=self.provider.now(),
        )
        exp.status = ExperimentStatus.OPEN
        exp.signal_details = {
            "entry": entry,
            "sl_dist": round(sl_dist, 2),
            "tp_dist": round(tp_dist, 2),
            "size_btc": round(size_btc, 8),
            "risk_usdt": round(risk_amount, 2),
            "spread_bps": round(tick.spread_bps, 2),
        }

    def _update_position(self, pos: BTCExperimentPosition, tick: CryptoTick) -> None:
        """MFE/MAE tracking."""
        current = tick.bid if pos.side == Side.BUY else tick.ask
        sl_dist = abs(pos.entry_price - pos.stop_loss)
        if sl_dist <= 0:
            return

        excursion = (current - pos.entry_price) if pos.side == Side.BUY else (pos.entry_price - current)

        if pos.mfe_price is None:
            pos.mfe_price = current
        if pos.mae_price is None:
            pos.mae_price = current

        if pos.side == Side.BUY:
            if current > pos.mfe_price:
                pos.mfe_price = current
            if current < pos.mae_price:
                pos.mae_price = current
        else:
            if current < pos.mfe_price:
                pos.mfe_price = current
            if current > pos.mae_price:
                pos.mae_price = current

        mfe_excursion = abs(pos.mfe_price - pos.entry_price) if pos.side == Side.BUY else abs(pos.entry_price - pos.mfe_price)
        mae_excursion = abs(pos.entry_price - pos.mae_price) if pos.side == Side.BUY else abs(pos.mae_price - pos.entry_price)
        pos.mfe_r = round(max(0, mfe_excursion / sl_dist), 4)
        pos.mae_r = round(max(0, mae_excursion / sl_dist), 4)

        # PnL
        pos.pnl_usdt = round(excursion * pos.size_btc, 2)
        pos.pnl_r = round(excursion / sl_dist, 4)

    def _check_exit(self, pos: BTCExperimentPosition, tick: CryptoTick) -> str | None:
        if pos.side == Side.BUY:
            if tick.bid <= pos.stop_loss:
                return ExperimentStatus.CLOSED_SL
            if pos.take_profit and tick.ask >= pos.take_profit:
                return ExperimentStatus.CLOSED_TP
        else:
            if tick.ask >= pos.stop_loss:
                return ExperimentStatus.CLOSED_SL
            if pos.take_profit and tick.bid <= pos.take_profit:
                return ExperimentStatus.CLOSED_TP
        return None

    def _close_position(self, pos: BTCExperimentPosition, tick: CryptoTick, status: str) -> None:
        exit_price = tick.bid if pos.side == Side.BUY else tick.ask
        pos.exit_price = exit_price
        pos.closed_at = self.provider.now()
        pos.status = status

        d = 1 if pos.side == Side.BUY else -1
        pnl = (exit_price - pos.entry_price) * d * pos.size_btc
        # Deduct fees
        fee = (pos.entry_price + exit_price) * pos.size_btc * self.fee_bps / 10000
        pos.pnl_usdt = round(pnl - fee, 2)

        sl_dist = abs(pos.entry_price - pos.stop_loss)
        if sl_dist > 0:
            pos.pnl_r = round((pnl - fee) / (sl_dist * pos.size_btc), 4)
