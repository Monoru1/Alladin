"""PositionMonitor : synchronise broker <-> base <-> journal <-> watchdog pour les positions ALLADIN.

Appelé à chaque cycle ET au démarrage (réconciliation). Ne ferme jamais rien lui-même.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from pydantic import BaseModel

from alladin.brokers.base import BrokerAdapter
from alladin.core.enums import DealEntry, Side
from alladin.core.errors import ExecutionBlockedError
from alladin.core.models import Deal, Position
from alladin.execution.models import comment_matches
from alladin.journal.models import EventType, TradeRecord
from alladin.journal.service import JournalService
from alladin.orchestration.state import RunContext, RunManager


class MonitorReport(BaseModel):
    open_positions: int = 0
    newly_closed: list[str] = []  # trade_id
    adopted: list[int] = []  # tickets
    sl_tp_changed: list[int] = []
    sl_removed: list[int] = []  # ALERTE : SL supprimé sur une position ALLADIN
    unresolved_closed: list[int] = []  # disparu de MT5 mais deals introuvables (retry)
    foreign_ignored: int = 0  # positions du compte n'appartenant pas à ALLADIN


class PositionMonitor:
    def __init__(
        self, broker: BrokerAdapter, manager: RunManager, journal: JournalService, run: RunContext
    ) -> None:
        self.broker, self.manager, self.journal, self.run = broker, manager, journal, run
        self.repo = manager.repo

    def _mine(self, positions: list[Position]) -> tuple[list[Position], int]:
        mine = []
        for p in positions:
            if p.magic == self.run.magic and comment_matches(
                p.comment, self.run.run_id, self.run.magic
            ):
                mine.append(p)
        return mine, len(positions) - len(mine)

    def sync(self, *, adopt: bool = False) -> MonitorReport:
        rid = self.run.run_id
        now = self.broker.now()
        acct = self.broker.account_info()
        binding = self.run.account_binding
        if binding and (binding.broker != self.broker.name or binding.account_ref != acct.login_masked
                        or binding.server != acct.server or binding.account_type != acct.account_type
                        or (binding.account_fingerprint is not None
                            and binding.account_fingerprint != acct.account_fingerprint)):
            raise ExecutionBlockedError("monitor: compte différent du binding du run")
        mine, foreign = self._mine(self.broker.positions())
        rep = MonitorReport(open_positions=len(mine), foreign_ignored=foreign)
        open_trades = {t.ticket: t for t in self.repo.trades_for_run(rid, "OPEN") if t.ticket is not None}
        live = {p.ticket: p for p in mine}

        # 1. positions vivantes : excursions, modifications SL/TP, adoption
        for ticket, pos in live.items():
            trade = open_trades.get(ticket)
            if trade is None:
                if adopt:
                    self._adopt(pos, now)
                    rep.adopted.append(ticket)
                continue
            deals = self._position_deals(ticket, trade.opened_at, now, trade.symbol)
            observed = pos.profit + sum(d.profit for d in deals)
            if not math.isfinite(observed):
                raise ValueError("excursion broker non finie")
            mae, mfe = min(trade.mae, observed), max(trade.mfe, observed)
            fields: dict[str, float | None] = {"excursion_samples": trade.excursion_samples + 1}
            if (mae, mfe) != (trade.mae, trade.mfe):
                fields.update(mae=mae, mfe=mfe)
            if pos.sl != trade.stop_loss or pos.tp != trade.take_profit:
                first_sl_removal = pos.sl is None and trade.stop_loss is not None
                if first_sl_removal:
                    rep.sl_removed.append(ticket)
                else:
                    rep.sl_tp_changed.append(ticket)
                self.journal.log(
                    rid,
                    EventType.POSITION_UPDATE,
                    {
                        "ticket": ticket,
                        "sl": {"from": trade.stop_loss, "to": pos.sl},
                        "tp": {"from": trade.take_profit, "to": pos.tp},
                        "alert": "SL SUPPRIMÉ" if first_sl_removal else None,
                    },
                )
                fields.update(stop_loss=pos.sl, take_profit=pos.tp)
            # Position toujours sans SL au broker (DB déjà synchronisée) : re-signaler
            if pos.sl is None and ticket not in rep.sl_removed:
                rep.sl_removed.append(ticket)
            if fields:
                self.repo.update_trade(trade.trade_id, **fields)

        # 2. positions disparues : clôturées (SL/TP/manuel/fermeture ALLADIN)
        for ticket, trade in open_trades.items():
            if ticket in live:
                continue
            if not self._finalise(trade, now):
                rep.unresolved_closed.append(ticket)
            else:
                rep.newly_closed.append(trade.trade_id)

        # 3. watchdog sur l'equity réelle
        acct = self.broker.account_info()
        self.manager.sync_watchdog(self.run, acct, len(live))
        return rep

    # ------------------------------------------------------------------ internes

    def _position_deals(self, ticket: int, since: datetime, now: datetime, symbol: str) -> list[Deal]:
        deals = self.broker.history_deals(since - timedelta(minutes=5), now + timedelta(minutes=5))
        return [d for d in deals if d.position_id == ticket and d.symbol == symbol
                and d.magic in (0, self.run.magic) and d.time <= now]

    def _finalise(self, trade: TradeRecord, now: datetime) -> bool:
        assert trade.ticket is not None
        deals = self._position_deals(trade.ticket, trade.opened_at, now, trade.symbol)
        if (len({d.ticket for d in deals}) != len(deals)
                or any(d.entry is DealEntry.INOUT for d in deals)
                or any(not all(math.isfinite(v) for v in (d.volume, d.price, d.profit, d.commission, d.fee, d.swap))
                       for d in deals)):
            return False
        outs = [d for d in deals if d.entry in (DealEntry.OUT, DealEntry.OUT_BY)]
        closed_volume = sum(d.volume for d in outs)
        if (any(d.volume <= 0 for d in outs)
                or (not trade.adopted and abs(closed_volume - trade.volume) > 1e-9)
                or (trade.adopted and closed_volume < trade.volume - 1e-9)):
            return False
        if not outs:
            return False  # historique pas encore disponible : on réessaiera au prochain cycle
        closing = max(outs, key=lambda d: (d.time, d.ticket))
        gross = sum(d.profit for d in deals)
        commission = sum(d.commission + d.fee for d in deals)
        swap = sum(d.swap for d in deals)
        net = gross + commission + swap
        r = net / trade.risk_amount if trade.risk_amount else 0.0
        acct = self.broker.account_info()
        reason = closing.close_reason.value
        self.repo.update_trade(
            trade.trade_id,
            status="CLOSED",
            closed_at=closing.time,
            close_price=closing.price,
            close_reason=reason,
            pnl_gross=gross,
            commission=commission,
            swap=swap,
            net_pnl=net,
            r_multiple=r,
            equity_after=acct.equity,
            mae=min(trade.mae, gross), mfe=max(trade.mfe, gross),
            excursion_samples=trade.excursion_samples + 1,
        )
        self.run.watchdog.record_closed_pnl(net, closing.time)
        self.manager.persist(self.run)
        self.journal.log(
            self.run.run_id,
            EventType.POSITION_CLOSED,
            {
                "trade_id": trade.trade_id,
                "proposal_id": trade.proposal_id,
                "opportunity_id": trade.opportunity_id,
                "ticket": trade.ticket,
                "symbol": trade.symbol,
                "side": trade.side,
                "close_reason": reason,
                "close_price": closing.price,
                "deal": closing.ticket,
                "pnl_gross": gross,
                "commission": commission,
                "swap": swap,
                "net_pnl": net,
                "r_multiple": round(r, 3),
                "mae": trade.mae,
                "mfe": trade.mfe,
                "equity_after": acct.equity,
            },
        )
        return True

    def _adopt(self, pos: Position, now: datetime) -> None:
        """Position ALLADIN retrouvée sans enregistrement (crash entre envoi et écriture) : on la rattache."""
        risk = 0.0
        trade = TradeRecord(
            trade_id=f"adopted-{pos.ticket}",
            workspace=self.run.workspace,
            run_id=self.run.run_id,
            symbol=pos.symbol,
            side=pos.side.value,
            strategy_id="UNKNOWN",
            strategy_version="?",
            regime="UNKNOWN",
            agent="unknown",
            status="OPEN",
            ticket=pos.ticket,
            volume=pos.volume,
            entry_requested=None,
            entry_executed=pos.price_open,
            stop_loss=pos.sl,
            take_profit=pos.tp,
            risk_amount=risk,
            risk_pct_of_wc=0.0,
            opened_at=pos.time_open or now,
            adopted=True,
        )
        self.repo.insert_trade(trade)
        self.journal.log(
            self.run.run_id,
            EventType.RECONCILE,
            {
                "action": "adopted",
                "ticket": pos.ticket,
                "symbol": pos.symbol,
                "side": Side(pos.side).value,
                "volume": pos.volume,
            },
        )

    def reconcile(self) -> MonitorReport:
        """Au démarrage : MT5 + base + journal. Adopte les positions orphelines, finalise les trades clos hors-ligne."""
        rep = self.sync(adopt=True)
        self.journal.log(
            self.run.run_id, EventType.RECONCILE, {"action": "summary", **rep.model_dump(mode="json")}
        )
        return rep
