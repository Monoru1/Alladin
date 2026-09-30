"""ExecutionService : seul point d'entrée vers un broker pour ouvrir/fermer.

Pipeline d'ouverture (aucune étape ne peut être sautée) :
  TradeIntent -> DEMO check -> ChallengeWatchdog -> RiskEngine(+PositionSizer) -> pré-validation broker
  -> envoi -> vérification du retcode ET de la position réellement ouverte -> journal.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from alladin.brokers.base import BrokerAdapter
from alladin.challenge.models import WatchdogReport
from alladin.core.approval import issue_close_token
from alladin.core.enums import OrderAction, Side
from alladin.core.errors import ExecutionBlockedError
from alladin.core.killswitch import KillSwitch
from alladin.core.models import AccountSnapshot, InstrumentSpec, OrderRequest, Position, TradeIntent
from alladin.execution.models import ExecStatus, ExecutionResult, make_comment, parse_comment
from alladin.journal.models import EventType, TradeRecord
from alladin.journal.service import JournalService
from alladin.orchestration.state import RunContext, RunManager
from alladin.risk.correlation import CorrelationMatrix
from alladin.risk.engine import RiskEngine
from alladin.risk.models import RejectCode, RiskContext, RiskDecision, RiskReason

DEFAULT_DEVIATION_POINTS = 20


class ExecutionService:
    def __init__(
        self,
        broker: BrokerAdapter,
        risk: RiskEngine,
        run: RunContext,
        manager: RunManager,
        journal: JournalService,
        killswitch: KillSwitch,
        *,
        clock: Callable[[], datetime] | None = None,
        deviation_points: int = DEFAULT_DEVIATION_POINTS,
        correlations: Callable[[], CorrelationMatrix | None] | None = None,
    ) -> None:
        self.broker, self.risk, self.run, self.manager = broker, risk, run, manager
        self.journal, self.killswitch = journal, killswitch
        self.clock = clock or (lambda: datetime.now(UTC))
        self.deviation = deviation_points
        self.correlations = correlations

    # ------------------------------------------------------------------ identification ALLADIN

    def owns(self, pos: Position) -> bool:
        """Une position appartient à ce run seulement si magic ET commentaire concordent."""
        parsed = parse_comment(pos.comment)
        return pos.magic == self.run.magic and parsed is not None and parsed[0] == self.run.run_id

    def my_positions(self) -> list[Position]:
        return [p for p in self.broker.positions() if self.owns(p)]

    # ------------------------------------------------------------------ ouverture

    def submit(self, intent: TradeIntent, *, dry_run: bool = False) -> ExecutionResult:
        rid = self.run.run_id
        self.journal.log(rid, EventType.TRADE_INTENT, intent.model_dump(mode="json"))

        # 1. DEMO uniquement — avant toute autre chose, fail closed
        try:
            account = self.broker.assert_demo()
        except ExecutionBlockedError as exc:
            return self._blocked(intent, str(exc))

        # 2. Watchdog sur l'equity réelle
        mine = self.my_positions()
        report = self.manager.sync_watchdog(self.run, account, len(mine))
        self.journal.log(rid, EventType.ACCOUNT_SNAPSHOT, account.model_dump(mode="json"))
        if report.close_positions_requested:
            self.close_all("run FAILED : fermeture contrôlée demandée par le profil")

        # 3. Contexte de risque (données broker réelles, jamais les chiffres de l'agent)
        ctx, problem = self._build_context(intent, account, report, mine)
        if ctx is None:
            decision = RiskDecision(
                intent_id=intent.intent_id,
                approved=False,
                reasons=[
                    RiskReason(
                        code=RejectCode.NOT_TRADABLE, message=problem or "contexte de risque indisponible"
                    )
                ],
            )
        else:
            decision = self.risk.evaluate(intent, ctx)
        self.journal.log(
            rid,
            EventType.RISK_DECISION,
            {
                "status": decision.status,
                **decision.model_dump(mode="json"),
                "reason_lines": decision.reason_lines(),
            },
        )
        if not decision.approved or decision.token is None:
            return ExecutionResult(
                status=ExecStatus.REJECTED_RISK,
                intent=intent,
                decision=decision,
                messages=decision.reason_lines(),
            )

        if dry_run:
            return ExecutionResult(
                status=ExecStatus.DRY_RUN_APPROVED,
                intent=intent,
                decision=decision,
                messages=list(decision.adjustments),
            )

        # 4. Requête broker construite ICI, à partir de la décision (volume = celui du PositionSizer)
        request = OrderRequest(
            action=OrderAction.OPEN,
            symbol=intent.instrument,
            side=intent.side,
            volume=decision.volume,
            entry_type=intent.entry_type,
            price=decision.entry_price,
            stop_loss=decision.stop_loss,
            take_profit=decision.take_profit,
            deviation_points=self.deviation,
            magic=self.run.magic,
            comment=make_comment(rid, intent.strategy_id),
        )
        check = self.broker.check_order(request)
        self.journal.log(
            rid,
            EventType.ORDER_PRECHECK,
            {"request": request.model_dump(mode="json"), "check": check.model_dump(mode="json")},
        )
        if not check.ok:
            return ExecutionResult(
                status=ExecStatus.REJECTED_BROKER,
                intent=intent,
                decision=decision,
                precheck=check,
                messages=[f"pré-validation broker refusée (retcode {check.retcode}) : {check.message}"],
            )

        # 5. Envoi
        self.journal.log(rid, EventType.ORDER_SENT, request.model_dump(mode="json"))
        try:
            result = self.broker.send_order(request, decision.token)
        except ExecutionBlockedError as exc:
            return self._blocked(intent, str(exc), decision)
        self.journal.log(rid, EventType.ORDER_RESULT, result.model_dump(mode="json"))
        if not result.accepted:
            return ExecutionResult(
                status=ExecStatus.REJECTED_BROKER,
                intent=intent,
                decision=decision,
                precheck=check,
                order=result,
                messages=[
                    f"ordre refusé par MT5 (retcode {result.retcode} {result.retcode_name}) : {result.message}"
                ],
            )

        # 6. Un envoi n'est pas une exécution : on vérifie la position réellement ouverte
        pos = next((p for p in self.broker.positions() if p.ticket == result.position_ticket), None)
        if pos is None:
            self.journal.log(
                rid,
                EventType.INFO,
                {"alert": "ordre accepté mais position introuvable", "ticket": result.position_ticket},
            )
            return ExecutionResult(
                status=ExecStatus.FAILED,
                intent=intent,
                decision=decision,
                precheck=check,
                order=result,
                messages=["ordre accepté mais position introuvable : réconciliation requise"],
            )
        if pos.sl is None:
            self.journal.log(
                rid,
                EventType.INFO,
                {"alert": "position ouverte SANS SL : fermeture d'urgence", "ticket": pos.ticket},
            )
            self._close(pos, "urgence : SL absent")
            return ExecutionResult(
                status=ExecStatus.FAILED,
                intent=intent,
                decision=decision,
                precheck=check,
                order=result,
                messages=["SL absent sur la position ouverte : fermée immédiatement"],
            )

        account_after = self.broker.account_info()
        trade = TradeRecord(
            trade_id=intent.intent_id,
            run_id=rid,
            symbol=intent.instrument,
            side=intent.side.value,
            strategy_id=intent.strategy_id,
            strategy_version=intent.strategy_version,
            regime=intent.market_regime.value,
            agent=intent.agent,
            status="OPEN",
            ticket=pos.ticket,
            volume=pos.volume,
            entry_requested=decision.entry_price,
            entry_executed=result.executed_price or pos.price_open,
            stop_loss=pos.sl,
            take_profit=pos.tp,
            risk_amount=decision.risk_amount,
            risk_pct_of_wc=decision.risk_pct_of_working_capital,
            spread_at_entry=result.spread_at_fill,
            slippage=result.slippage,
            cycle_id=self.journal.current_cycle,
            opened_at=result.executed_at,
            equity_after=account_after.equity,
        )
        self.manager.repo.insert_trade(trade)
        self.run.watchdog.record_trade_opened(self.clock())
        self.manager.persist(self.run)
        self.journal.log(
            rid,
            EventType.POSITION_OPENED,
            {
                "trade": trade.model_dump(mode="json"),
                "deal": result.deal,
                "order": result.order,
                "retcode": result.retcode,
                "commission": result.commission,
            },
        )
        return ExecutionResult(
            status=ExecStatus.EXECUTED,
            intent=intent,
            decision=decision,
            precheck=check,
            order=result,
            trade_id=trade.trade_id,
            position_ticket=pos.ticket,
            messages=list(decision.adjustments),
        )

    def _blocked(
        self, intent: TradeIntent, message: str, decision: RiskDecision | None = None
    ) -> ExecutionResult:
        self.journal.log(
            self.run.run_id, EventType.EXECUTION_BLOCKED, {"intent_id": intent.intent_id, "reason": message}
        )
        return ExecutionResult(
            status=ExecStatus.BLOCKED, intent=intent, decision=decision, messages=[message]
        )

    def _build_context(
        self, intent: TradeIntent, account: AccountSnapshot, report: WatchdogReport, mine: list[Position]
    ) -> tuple[RiskContext | None, str | None]:
        self.broker.select_symbol(intent.instrument)
        spec = self.broker.symbol_spec(intent.instrument)
        tick = self.broker.tick(intent.instrument)
        if spec is None:
            return None, f"instrument {intent.instrument} inconnu du broker"
        if tick is None or tick.bid <= 0 or tick.ask <= 0:
            return None, f"aucun tick valide pour {intent.instrument}"
        specs: dict[str, InstrumentSpec] = {}
        for p in mine:
            s = self.broker.symbol_spec(p.symbol)
            if s is not None:
                specs[p.symbol] = s
        price = tick.ask if intent.side is Side.BUY else tick.bid
        mpl = self.broker.calc_margin(intent.instrument, intent.side is Side.BUY, 1.0, price)
        return (
            RiskContext(
                now=self.clock(),
                account=account,
                spec=spec,
                tick=tick,
                positions=mine,
                specs=specs,
                watchdog=report,
                kill_switch_active=self.killswitch.is_active(),
                margin_per_lot=mpl,
                correlations=self.correlations() if self.correlations else None,
            ),
            None,
        )

    # ------------------------------------------------------------------ fermeture

    def _close(self, pos: Position, reason: str) -> None:
        rid = self.run.run_id
        tick = self.broker.tick(pos.symbol)
        request = OrderRequest(
            action=OrderAction.CLOSE,
            symbol=pos.symbol,
            side=pos.side.opposite,
            volume=pos.volume,
            price=(tick.bid if pos.side is Side.BUY else tick.ask) if tick else None,
            deviation_points=self.deviation,
            magic=pos.magic,
            comment=pos.comment,
            position_ticket=pos.ticket,
        )
        self.journal.log(
            rid, EventType.ORDER_SENT, {**request.model_dump(mode="json"), "close_reason": reason}
        )
        try:
            result = self.broker.send_order(request, issue_close_token(rid, pos.symbol, pos.volume))
        except ExecutionBlockedError as exc:
            self.journal.log(
                rid, EventType.EXECUTION_BLOCKED, {"close_ticket": pos.ticket, "reason": str(exc)}
            )
            return
        self.journal.log(
            rid, EventType.ORDER_RESULT, {**result.model_dump(mode="json"), "close_reason": reason}
        )

    def close_position(self, ticket: int, reason: str = "fermeture manuelle") -> bool:
        pos = next((p for p in self.my_positions() if p.ticket == ticket), None)
        if pos is None:
            return False  # jamais une position qui n'appartient pas à ALLADIN/ce run
        self._close(pos, reason)
        return True

    def close_all(self, reason: str) -> int:
        """Fermeture explicite des positions de CE run uniquement (jamais implicite au redémarrage)."""
        n = 0
        for p in self.my_positions():
            self._close(p, reason)
            n += 1
        return n
