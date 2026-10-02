"""Paper Experiment Engine : simule des trades PAPER sans envoyer d'ordre reel.

Chaque trade paper est suivi avec les prix reels du broker.
P&L, MFE, MAE sont calcules au fil du temps.
Isole du journal live (paper_run_id distinct).

Persistence : les positions sont sauvegardees en base via JournalRepository
et restaurees au redemarrage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from alladin.brokers.base import BrokerAdapter
from alladin.core.enums import Side
from alladin.core.models import TradeIntent

if TYPE_CHECKING:
    from alladin.journal.repository import JournalRepository
    from alladin.risk.models import RiskDecision


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
    close_reason: str | None = None

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
        self.close_reason = status
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
            "close_reason": self.close_reason,
            "pnl_pips": round(self.pnl_pips, 2),
            "mfe_pips": round(self.mfe_pips, 2),
            "mae_pips": round(self.mae_pips, 2),
        }

    def to_persistence(self) -> dict[str, Any]:
        """Format pour insert/update dans paper_positions table."""
        import json

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
            "close_reason": self.close_reason,
            "pnl_pips": self.pnl_pips,
            "mfe_pips": self.mfe_pips,
            "mae_pips": self.mae_pips,
            "intent_json": json.dumps(self.intent, default=str) if self.intent else None,
        }

    @classmethod
    def from_persistence(cls, d: dict[str, Any]) -> PaperPosition:
        """Reconstruit depuis une ligne de la table paper_positions."""
        import json
        from datetime import datetime as dt

        intent = json.loads(d["intent_json"]) if d.get("intent_json") else {}
        opened = dt.fromisoformat(d["opened_at"]) if isinstance(d["opened_at"], str) else d["opened_at"]
        closed = dt.fromisoformat(d["closed_at"]) if isinstance(d.get("closed_at"), str) and d["closed_at"] else None
        return cls(
            paper_id=d["paper_id"],
            run_id=d["run_id"],
            cycle_id=d.get("cycle_id", ""),
            symbol=d["symbol"],
            side=Side(d["side"]),
            volume=d["volume"],
            entry_price=d["entry_price"],
            sl=d["sl"],
            tp=d.get("tp"),
            opened_at=opened,
            exit_price=d.get("exit_price"),
            closed_at=closed,
            status=d.get("status", "OPEN"),
            close_reason=d.get("close_reason"),
            pnl_pips=d.get("pnl_pips", 0.0),
            mfe_pips=d.get("mfe_pips", 0.0),
            mae_pips=d.get("mae_pips", 0.0),
            intent=intent,
        )


class PaperExperimentEngine:
    """Gere les positions paper en mode PAPER.

    - Ouvre des positions a partir de TradeIntent (sans envoyer d'ordre)
    - Suit le P&L en temps reel via les ticks broker
    - Ferme automatiquement sur SL/TP
    - Calcule MFE/MAE pour chaque trade
    - Persiste les positions en base pour survie au restart
    """

    def __init__(self, broker: BrokerAdapter, run_id: str, *, repo: JournalRepository | None = None) -> None:
        self.broker = broker
        self.run_id = run_id
        self._repo = repo
        self._open: dict[str, PaperPosition] = {}  # paper_id -> position
        self._closed: list[PaperPosition] = []

    def restore(self) -> int:
        """Restaure les positions ouvertes depuis la persistance. Retourne le nombre restaure."""
        if self._repo is None:
            return 0
        rows = self._repo.list_paper_positions(self.run_id, status="OPEN")
        for row in rows:
            pos = PaperPosition.from_persistence(row)
            self._open[pos.paper_id] = pos
        closed_rows = self._repo.list_paper_positions(self.run_id, status=None)
        for row in closed_rows:
            if row["status"] != "OPEN":
                self._closed.append(PaperPosition.from_persistence(row))
        return len(rows)

    def open_position(
        self,
        intent: TradeIntent,
        cycle_id: str,
        *,
        decision: RiskDecision | None = None,
    ) -> PaperPosition:
        """Simule l'ouverture d'une position paper a partir d'un intent.

        Si un RiskDecision est fourni, utilise le volume/SL/TP ajustes par le RiskEngine.
        """
        now = self.broker.now()
        tick = self.broker.tick(intent.instrument)
        if tick is None:
            raise RuntimeError(f"no tick for {intent.instrument}")
        entry = tick.ask if intent.side == Side.BUY else tick.bid

        # Utiliser les valeurs ajustees par le RiskEngine si disponibles
        volume = decision.volume if decision else 0.01
        raw_sl = decision.stop_loss if decision else intent.stop_loss
        sl = raw_sl if raw_sl is not None else entry * 0.99
        tp = decision.take_profit if decision else intent.take_profit

        pos = PaperPosition(
            paper_id=f"PAPER-{uuid4().hex[:8]}",
            run_id=self.run_id,
            cycle_id=cycle_id,
            symbol=intent.instrument,
            side=intent.side,
            volume=volume,
            entry_price=entry,
            sl=sl,
            tp=tp,
            opened_at=now,
            intent=intent.model_dump(mode="json"),
        )
        self._open[pos.paper_id] = pos
        self._persist_open(pos)
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
                self._persist_close(pos)
            else:
                self._persist_excursion(pos)
        return newly_closed

    def close_position_by_id(self, paper_id: str, reason: str = "CLOSED_MANUAL") -> PaperPosition | None:
        """Fermeture explicite d'une position paper."""
        pos = self._open.get(paper_id)
        if pos is None:
            return None
        now = self.broker.now()
        tick = self.broker.tick(pos.symbol)
        if tick is None:
            return None
        spec = self.broker.symbol_spec(pos.symbol)
        point = spec.point if spec else 0.00001
        exit_price = tick.bid if pos.side == Side.BUY else tick.ask
        pos.close(exit_price, reason, now, point)
        del self._open[paper_id]
        self._closed.append(pos)
        self._persist_close(pos)
        return pos

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

    # ------------------------------------------------------------------ persistence helpers

    def _persist_open(self, pos: PaperPosition) -> None:
        if self._repo is None:
            return
        self._repo.insert_paper_position(pos.to_persistence())

    def _persist_close(self, pos: PaperPosition) -> None:
        if self._repo is None:
            return
        self._repo.update_paper_position(
            pos.paper_id,
            exit_price=pos.exit_price,
            closed_at=pos.closed_at.isoformat() if pos.closed_at else None,
            status=pos.status,
            close_reason=pos.close_reason,
            pnl_pips=pos.pnl_pips,
            mfe_pips=pos.mfe_pips,
            mae_pips=pos.mae_pips,
        )

    def _persist_excursion(self, pos: PaperPosition) -> None:
        if self._repo is None:
            return
        self._repo.update_paper_position(
            pos.paper_id,
            mfe_pips=pos.mfe_pips,
            mae_pips=pos.mae_pips,
        )
