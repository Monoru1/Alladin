"""Paper Experiment Engine : simule des trades PAPER sans envoyer d'ordre reel.

Chaque trade paper est suivi avec les prix reels du broker.
P&L, MFE, MAE sont calcules au fil du temps.
Isole du journal live (paper_run_id distinct).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from alladin.brokers.base import BrokerAdapter
from alladin.core.enums import Side
from alladin.core.models import TradeIntent


class PaperStatus(str):
    OPEN = "OPEN"
    CLOSED_SL = "CLOSED_SL"
    CLOSED_TP = "CLOSED_TP"
    CLOSED_MANUAL = "CLOSED_MANUAL"
    EXPIRED = "EXPIRED"


@dataclass
class PaperPosition:
    """Position paper en cours ou terminee."""

    paper_id: str
    run_id: str
    cycle_id: str
    symbol: str
    side: Side
    volume: float
    entry_price: float
    sl: float
    tp: float | None
    opened_at: datetime
    intent: dict[str, Any] = field(default_factory=dict)

    # Filled at close
    exit_price: float | None = None
    closed_at: datetime | None = None
    status: str = "OPEN"

    # Analytics
    pnl_pips: float = 0.0
    mfe_pips: float = 0.0  # max favorable excursion
    mae_pips: float = 0.0  # max adverse excursion (positif = distance defavorable)

    def mark_price(self, bid: float, ask: float, point: float) -> None:
        """Met a jour MFE/MAE avec le prix courant."""
        current = bid if self.side == Side.BUY else ask
        entry = self.entry_price
        excursion = (current - entry) / point if self.side == Side.BUY else (entry - current) / point
        if excursion > self.mfe_pips:
            self.mfe_pips = excursion
        if excursion < -self.mae_pips:
            self.mae_pips = -excursion

    def check_exit(self, bid: float, ask: float, point: float) -> str | None:
        """Retourne le statut de cloture si SL/TP atteint, sinon None."""
        if self.side == Side.BUY:
            if bid <= self.sl:
                return PaperStatus.CLOSED_SL
            if self.tp is not None and bid >= self.tp:
                return PaperStatus.CLOSED_TP
        else:
            if ask >= self.sl:
                return PaperStatus.CLOSED_SL
            if self.tp is not None and ask <= self.tp:
                return PaperStatus.CLOSED_TP
        return None

    def close(self, exit_price: float, status: str, now: datetime, point: float) -> None:
        self.exit_price = exit_price
        self.closed_at = now
        self.status = status
        if self.side == Side.BUY:
            self.pnl_pips = (exit_price - self.entry_price) / point
        else:
            self.pnl_pips = (self.entry_price - exit_price) / point

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "run_id": self.run_id,
            "cycle_id": self.cycle_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "volume": self.volume,
            "entry_price": self.entry_price,
            "sl": self.sl,
            "tp": self.tp,
            "opened_at": self.opened_at.isoformat(),
            "exit_price": self.exit_price,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
            "status": self.status,
            "pnl_pips": round(self.pnl_pips, 2),
            "mfe_pips": round(self.mfe_pips, 2),
            "mae_pips": round(self.mae_pips, 2),
        }


class PaperExperimentEngine:
    """Gere les positions paper en mode PAPER.

    - Ouvre des positions a partir de TradeIntent (sans envoyer d'ordre)
    - Suit le P&L en temps reel via les ticks broker
    - Ferme automatiquement sur SL/TP
    - Calcule MFE/MAE pour chaque trade
    """

    def __init__(self, broker: BrokerAdapter, run_id: str) -> None:
        self.broker = broker
        self.run_id = run_id
        self._open: dict[str, PaperPosition] = {}  # paper_id -> position
        self._closed: list[PaperPosition] = []

    def open_position(self, intent: TradeIntent, cycle_id: str) -> PaperPosition:
        """Simule l'ouverture d'une position paper a partir d'un intent."""
        now = self.broker.now()
        tick = self.broker.tick(intent.instrument)
        if tick is None:
            raise RuntimeError(f"no tick for {intent.instrument}")
        entry = tick.ask if intent.side == Side.BUY else tick.bid
        pos = PaperPosition(
            paper_id=f"PAPER-{uuid4().hex[:8]}",
            run_id=self.run_id,
            cycle_id=cycle_id,
            symbol=intent.instrument,
            side=intent.side,
            volume=0.01,
            entry_price=entry,
            sl=intent.stop_loss or entry * 0.99,
            tp=intent.take_profit,
            opened_at=now,
            intent=intent.model_dump(mode="json"),
        )
        self._open[pos.paper_id] = pos
        return pos

    def tick_all(self) -> list[PaperPosition]:
        """Met a jour toutes les positions ouvertes, ferme celles qui ont atteint SL/TP.

        Retourne la liste des positions fermees lors de cet appel.
        """
        now = self.broker.now()
        newly_closed: list[PaperPosition] = []
        for paper_id, pos in list(self._open.items()):
            tick = self.broker.tick(pos.symbol)
            if tick is None:
                continue
            spec = self.broker.symbol_spec(pos.symbol)
            point = spec.point if spec else 0.00001
            pos.mark_price(tick.bid, tick.ask, point)
            exit_status = pos.check_exit(tick.bid, tick.ask, point)
            if exit_status:
                exit_price = tick.bid if pos.side == Side.BUY else tick.ask
                pos.close(exit_price, exit_status, now, point)
                del self._open[paper_id]
                self._closed.append(pos)
                newly_closed.append(pos)
        return newly_closed

    def open_positions(self) -> list[PaperPosition]:
        return list(self._open.values())

    def closed_positions(self) -> list[PaperPosition]:
        return list(self._closed)

    def stats(self) -> dict[str, Any]:
        closed = self._closed
        if not closed:
            return {"trades": 0, "open": len(self._open)}
        wins = [p for p in closed if p.pnl_pips > 0]
        losses = [p for p in closed if p.pnl_pips <= 0]
        total_pnl = sum(p.pnl_pips for p in closed)
        avg_mfe = sum(p.mfe_pips for p in closed) / len(closed)
        avg_mae = sum(p.mae_pips for p in closed) / len(closed)
        return {
            "trades": len(closed),
            "open": len(self._open),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(closed), 3),
            "total_pnl_pips": round(total_pnl, 2),
            "avg_mfe_pips": round(avg_mfe, 2),
            "avg_mae_pips": round(avg_mae, 2),
        }
