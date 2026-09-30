"""OrchestrationEngine : un cycle = monitor -> scan -> régime -> routeur -> agent -> intent -> Risk -> exécution.

Le moteur ne parle JAMAIS au broker pour trader : tout passe par ExecutionService (qui impose
DEMO, watchdog, RiskEngine, sizing, pré-validation, vérification). NO TRADE est une issue normale.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from alladin.agents.base import AgentAdapter, AgentIntentDraft, AgentRequest
from alladin.brokers.base import BrokerAdapter
from alladin.core.enums import DecisionKind, RunState
from alladin.core.errors import AlladinError
from alladin.core.models import TradeIntent
from alladin.execution.models import ExecStatus
from alladin.execution.service import ExecutionService
from alladin.journal.models import EventType
from alladin.journal.service import JournalService
from alladin.market.models import ScanReport
from alladin.market.scanner import MarketScanner
from alladin.orchestration.monitor import PositionMonitor
from alladin.orchestration.state import RunContext, RunManager
from alladin.risk import sizing
from alladin.strategies.base import StrategyContext
from alladin.strategies.router import StrategyRouter

log = logging.getLogger(__name__)

_CTX_METRICS = ("atr", "er20", "rsi14", "dist_ema50_atr", "momentum_atr", "atr_pct_rank", "tr_last_atr")


class CycleOutcome(BaseModel):
    cycle: int
    run_state: str
    decision: str  # TRADE | NO_TRADE | HALTED
    reason: str = ""
    shortlist: list[str] = []
    result: dict[str, Any] | None = None


class OrchestrationEngine:
    def __init__(
        self,
        *,
        broker: BrokerAdapter,
        run: RunContext,
        manager: RunManager,
        journal: JournalService,
        scanner: MarketScanner,
        router: StrategyRouter,
        agent: AgentAdapter,
        execution: ExecutionService,
        monitor: PositionMonitor,
        execute: bool = False,
    ) -> None:
        self.broker, self.run, self.manager, self.journal = broker, run, manager, journal
        self.scanner, self.router, self.agent = scanner, router, agent
        self.execution, self.monitor = execution, monitor
        self.execute = execute  # False => dry-run : le RiskEngine évalue, rien n'est envoyé
        self._cycle = 0

    # ------------------------------------------------------------------ un cycle

    def run_cycle(self) -> CycleOutcome:
        self._cycle += 1
        rid = self.run.run_id

        # 1. positions & watchdog d'abord
        rep = self.monitor.sync()
        for ticket in rep.sl_removed:
            self.journal.log(
                rid, EventType.INFO, {"alert": "SL supprimé : fermeture de la position", "ticket": ticket}
            )
            self.execution.close_position(ticket, "SL supprimé")
        state = self.run.watchdog.run_state
        if self.execution.killswitch.is_active() or state not in (RunState.RUNNING, RunState.TARGET_REACHED):
            why = "kill switch actif" if self.execution.killswitch.is_active() else f"run {state.value}"
            return CycleOutcome(cycle=self._cycle, run_state=state.value, decision="HALTED", reason=why)

        # 2. marché
        scan = self.scanner.scan()
        self.journal.log(rid, EventType.SCAN, scan.summary())

        # 3. régime -> routeur -> signaux de stratégies
        signals, evaluated = self._signals(scan)

        # 4. agent
        request = AgentRequest(run_id=rid, context=self._context(scan, signals))
        self.journal.log(rid, EventType.AGENT_REQUEST, {"agent": self.agent.name, "context": request.context})
        response = self.agent.propose(request)
        self.journal.log(rid, EventType.AGENT_RESPONSE, response.model_dump(mode="json"))

        shortlist = [c.symbol for c in scan.candidates]
        if not response.ok or response.decision is None:
            return self._no_trade(
                scan,
                evaluated,
                response.agent,
                f"réponse agent inexploitable : {'; '.join(response.errors)}",
                shortlist,
            )
        dec = response.decision
        if dec.decision is DecisionKind.NO_TRADE or dec.intent is None:
            return self._no_trade(
                scan, evaluated, response.agent, dec.reason or "l'agent ne propose aucun trade", shortlist
            )

        # 5. validation de l'intention (rien de ce que dit l'agent n'est digne de confiance)
        intent, problems = self._intent_from_draft(dec.intent, response.agent, shortlist)
        if intent is None:
            self.journal.log(
                rid,
                EventType.INTENT_REJECTED_SCHEMA,
                {"agent": response.agent, "errors": problems, "draft": dec.intent.model_dump(mode="json")},
            )
            return self._no_trade(
                scan, evaluated, response.agent, f"intent refusé : {'; '.join(problems)}", shortlist
            )

        # 6. exécution (ou dry-run)
        result = self.execution.submit(intent, dry_run=not self.execute)
        self.monitor.sync()
        return CycleOutcome(
            cycle=self._cycle,
            run_state=self.run.watchdog.run_state.value,
            decision="TRADE"
            if result.status in (ExecStatus.EXECUTED, ExecStatus.DRY_RUN_APPROVED)
            else "NO_TRADE",
            reason=f"{result.status.value}: {'; '.join(result.messages)}",
            shortlist=shortlist,
            result=result.model_dump(mode="json", exclude={"intent"}),
        )

    def _no_trade(
        self,
        scan: ScanReport,
        evaluated: dict[str, list[str]],
        agent: str | None,
        reason: str,
        shortlist: list[str],
    ) -> CycleOutcome:
        self.journal.no_trade(
            self.run.run_id,
            studied=sorted(set(scan.rejected) | set(shortlist)),
            candidates=shortlist,
            strategies_evaluated=evaluated,
            rejections=scan.rejected,
            agent=agent,
            reason=reason,
        )
        return CycleOutcome(
            cycle=self._cycle,
            run_state=self.run.watchdog.run_state.value,
            decision="NO_TRADE",
            reason=reason,
            shortlist=shortlist,
        )

    # ------------------------------------------------------------------ étapes

    def _signals(self, scan: ScanReport) -> tuple[list[tuple[TradeIntent, float]], dict[str, list[str]]]:
        out: list[tuple[TradeIntent, float]] = []
        evaluated: dict[str, list[str]] = {}
        now = self.broker.now()
        for cand in scan.candidates:
            decision, strategies = self.router.route(cand)
            self.journal.log(self.run.run_id, EventType.ROUTING, decision.model_dump(mode="json"))
            evaluated[cand.symbol] = decision.selected
            for strat in strategies:
                sig = strat.evaluate(StrategyContext(run_id=self.run.run_id, now=now, candidate=cand))
                if sig is None:
                    continue
                intent = strat.to_intent(
                    sig, StrategyContext(run_id=self.run.run_id, now=now, candidate=cand)
                )
                self.journal.log(
                    self.run.run_id,
                    EventType.SIGNAL,
                    {
                        "strategy": f"{strat.id}@{strat.version}",
                        **sig.model_dump(mode="json"),
                        "symbol": cand.symbol,
                    },
                )
                out.append((intent, cand.score))
        return out, evaluated

    def _context(self, scan: ScanReport, signals: list[tuple[TradeIntent, float]]) -> dict[str, Any]:
        acct = self.broker.account_info()
        wd = self.run.watchdog
        rules = self.run.profile.risk
        wc = sizing.working_capital(acct.equity, rules.working_capital_pct)
        return {
            "now": self.broker.now().isoformat(),
            "account": {
                "equity": round(acct.equity, 2),
                "currency": acct.currency,
                "working_capital": round(wc, 2),
                "max_trade_risk": round(
                    sizing.max_trade_risk(wc, rules.max_trade_risk_pct_of_working_capital), 2
                ),
                "phase": wd.phase_number,
                "phase_target_pct": self.run.profile.phases[wd.state.phase_index].profit_target_pct,
                "run_state": wd.run_state.value,
                "open_positions": [
                    {"symbol": p.symbol, "side": p.side.value, "profit": round(p.profit, 2)}
                    for p in self.execution.my_positions()
                ],
            },
            "rules": {
                "max_trade_risk_pct_of_working_capital": rules.max_trade_risk_pct_of_working_capital,
                "stop_loss_required": True,
                "volume": "calculé par le RiskEngine, ne pas fournir",
            },
            "shortlist": [
                {
                    "symbol": c.symbol,
                    "category": c.category.value,
                    "regime": c.regime.value,
                    "regime_reasons": c.regime_reasons,
                    "score": c.score,
                    "bias": c.bias.value if c.bias else None,
                    "session": c.session,
                    "spread_atr_ratio": round(c.spread_atr_ratio, 3),
                    "tf_trend": c.tf_trend,
                    "metrics": {k: round(v, 4) for k, v in c.metrics.items() if k in _CTX_METRICS},
                }
                for c in scan.candidates
            ],
            "signals": [
                {
                    "draft": AgentIntentDraft.model_validate(
                        i.model_dump(include=set(AgentIntentDraft.model_fields))
                    ).model_dump(mode="json"),
                    "candidate_score": s,
                }
                for i, s in signals
            ],
            "strategies_available": self.router.registry.catalogue(),
        }

    def _intent_from_draft(
        self, draft: AgentIntentDraft, agent: str, shortlist: list[str]
    ) -> tuple[TradeIntent | None, list[str]]:
        problems: list[str] = []
        if draft.instrument not in shortlist:
            problems.append(f"instrument {draft.instrument} absent de la shortlist scannée")
        strat = self.router.registry.get(draft.strategy_id)
        if strat is None:
            problems.append(f"stratégie {draft.strategy_id} inconnue ou désactivée")
        elif strat.version != draft.strategy_version:
            problems.append(f"version {draft.strategy_version} != {strat.version} pour {draft.strategy_id}")
        if problems:
            return None, problems
        try:
            return draft.to_intent(run_id=self.run.run_id, agent=agent, now=self.broker.now()), []
        except ValueError as exc:
            return None, [str(exc)]

    # ------------------------------------------------------------------ boucle

    def run_loop(
        self,
        interval_s: float,
        max_cycles: int | None = None,
        on_cycle: Callable[[CycleOutcome], None] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        failures = 0
        n = 0
        while max_cycles is None or n < max_cycles:
            n += 1
            try:
                outcome = self.run_cycle()
                failures = 0
            except AlladinError as exc:  # broker indisponible, etc.
                failures += 1
                self.journal.log(
                    self.run.run_id,
                    EventType.INFO,
                    {"alert": "cycle en erreur", "error": str(exc), "consecutive": failures},
                )
                if failures >= 3 and self.run.watchdog.run_state is RunState.RUNNING:
                    self.manager.pause(self.run, f"3 cycles en erreur consécutifs : {exc}")
                outcome = CycleOutcome(
                    cycle=self._cycle,
                    run_state=self.run.watchdog.run_state.value,
                    decision="HALTED",
                    reason=str(exc),
                )
            if on_cycle:
                on_cycle(outcome)
            if self.run.watchdog.run_state.is_terminal or (
                outcome.decision == "HALTED" and self.run.watchdog.run_state is RunState.PAUSED
            ):
                break
            if max_cycles is None or n < max_cycles:
                sleep(interval_s)
