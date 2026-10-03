"""OrchestrationEngine : un cycle = monitor -> scan -> régime -> routeur -> agent -> intent -> Risk -> exécution.

Le moteur ne parle JAMAIS au broker pour trader : tout passe par ExecutionService (qui impose
DEMO, watchdog, RiskEngine, sizing, pré-validation, vérification). NO TRADE est une issue normale.
"""

from __future__ import annotations

import logging
import signal
import time
from collections.abc import Callable
from datetime import timedelta
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from alladin.agents.base import AgentAdapter, AgentIntentDraft
from alladin.brain import Action, ActionProposal, Brain, BrainContext, ClassicBrainAdapter
from alladin.brokers.base import BrokerAdapter
from alladin.core.enums import RunMode, RunState, Side
from alladin.core.errors import AlladinError
from alladin.core.models import TradeIntent
from alladin.execution.models import ExecStatus
from alladin.execution.service import ExecutionService
from alladin.journal.models import EventType
from alladin.journal.service import JournalService
from alladin.market.models import ScanReport
from alladin.market.opportunity import Opportunity, OpportunityStatus, opportunity_identity
from alladin.market.paper import PaperExperimentEngine
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
    decision: str  # TRADE | NO_TRADE | HOLD | HALTED
    reason: str = ""
    shortlist: list[str] = []
    result: dict[str, Any] | None = None
    cycle_id: str | None = None


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
        run_mode: RunMode = RunMode.OBSERVE,
        execute: bool = False,  # rétrocompatibilité : remplacé par run_mode
        paper_engine: PaperExperimentEngine | None = None,
        brain: Brain | None = None,
    ) -> None:
        self.broker, self.run, self.manager, self.journal = broker, run, manager, journal
        self.scanner, self.router, self.agent = scanner, router, agent
        self.execution, self.monitor = execution, monitor
        # run_mode prend le dessus sur le flag legacy execute
        if execute and run_mode is RunMode.OBSERVE:
            run_mode = RunMode.DEMO
        self.run_mode = run_mode
        self.execute = run_mode is RunMode.DEMO  # compatibilité interne
        self.paper_engine = paper_engine
        self.brain = brain or ClassicBrainAdapter(agent)
        self._cycle = 0
        self._stop_requested = False

    # ------------------------------------------------------------------ un cycle

    def run_cycle(self) -> CycleOutcome:
        """Un cycle complet, tracé de bout en bout par un `cycle_id` unique (tous les événements le portent)."""
        self._cycle += 1
        cycle_id = f"CYC-{self.broker.now():%Y%m%d-%H%M%S}-{uuid4().hex[:4]}"
        self.journal.current_cycle = cycle_id
        try:
            self.journal.log(
                self.run.run_id,
                EventType.CYCLE_START,
                {"cycle": self._cycle, "agent": self.agent.name, "execute": self.execute},
            )
            outcome = self._run_cycle(cycle_id)
            outcome.cycle_id = cycle_id
            self.journal.log(
                self.run.run_id,
                EventType.CYCLE_END,
                {
                    "decision": outcome.decision,
                    "reason": outcome.reason,
                    "run_state": outcome.run_state,
                    "shortlist": outcome.shortlist,
                },
            )
            return outcome
        finally:
            self.journal.current_cycle = None

    def _run_cycle(self, cycle_id: str) -> CycleOutcome:
        rid = self.run.run_id

        # 0. PAPER : tick les positions paper avant le scan (SL/TP auto)
        if self.run_mode is RunMode.PAPER and self.paper_engine is not None:
            for pc in self.paper_engine.tick_all():
                self.journal.log(
                    rid,
                    EventType.POSITION_CLOSED,
                    {"paper": True, **pc.to_dict()},
                )

        # 1. positions & watchdog d'abord
        rep = self.monitor.sync()
        for ticket in rep.sl_removed:
            if self.run_mode is RunMode.DEMO:
                # DEMO : fermeture protectrice autorisee
                self.journal.log(
                    rid, EventType.INFO,
                    {"alert": "SL supprimé : fermeture de la position", "ticket": ticket},
                )
                if not self.execution.close_position(ticket, "SL supprimé"):
                    self.journal.log(
                        rid,
                        EventType.INFO,
                        {"alert": "fermeture protectrice échouée — position reste sans SL",
                         "ticket": ticket},
                    )
            else:
                # OBSERVE / PAPER : aucun send_order, alerte critique seulement
                self.journal.log(
                    rid,
                    EventType.INFO,
                    {"alert": "CRITIQUE : position sans SL détectée, intervention humaine requise "
                              "(mode strict, aucun ordre envoyé)",
                     "ticket": ticket, "run_mode": self.run_mode.value},
                )
        state = self.run.watchdog.run_state
        if self.execution.killswitch.is_active() or state not in (RunState.RUNNING, RunState.TARGET_REACHED):
            why = "kill switch actif" if self.execution.killswitch.is_active() else f"run {state.value}"
            return CycleOutcome(cycle=self._cycle, run_state=state.value, decision="HALTED", reason=why)

        # 2. marché
        acct = self.broker.account_info()
        budget = sizing.max_trade_risk(
            sizing.working_capital(acct.equity, self.run.profile.risk.working_capital_pct),
            self.run.profile.risk.max_trade_risk_pct_of_working_capital,
        )
        scan = self.scanner.scan(cycle_id=cycle_id, max_trade_risk=budget)
        self.journal.log(rid, EventType.SCAN, scan.summary())

        # 3. créer les Opportunity objects à partir du scan
        opportunities = self._build_opportunities(scan, cycle_id)

        # 4. régime -> routeur -> signaux de stratégies
        signals, evaluated = self._signals(scan)

        # 5. cerveau : le contexte ne contient ni broker ni service d'exécution.
        shortlist = [c.symbol for c in scan.candidates]
        try:
            context = BrainContext(
                run_id=rid, cycle_id=cycle_id, timestamp=self.broker.now(),
                opportunities={o.symbol: o.opportunity_id for o in opportunities
                               if o.status is OpportunityStatus.QUALIFIED},
                market=self._context(scan, signals),
            )
            if isinstance(self.brain, ClassicBrainAdapter):
                self.journal.log(rid, EventType.AGENT_REQUEST,
                                 {"agent": self.agent.name, "context": context.market})
            raw = self.brain.decide(context)
            if isinstance(self.brain, ClassicBrainAdapter) and self.brain.last_response is not None:
                self.journal.log(rid, EventType.AGENT_RESPONSE,
                                 self.brain.last_response.model_dump(mode="json"))
            proposal = ActionProposal.model_validate(raw.model_dump(mode="python"))
            position_links = {p["ticket"]: p for p in context.market["account"]["open_positions"]}
            if (proposal.run_id != rid or proposal.cycle_id != cycle_id
                    or proposal.source_id != self.brain.source_id
                    or proposal.source_version != self.brain.source_version
                    or proposal.timestamp != context.timestamp
                    or (proposal.action in (Action.LONG, Action.SHORT)
                        and context.opportunities.get(proposal.symbol or "") != proposal.opportunity_id)
                    or (proposal.action is Action.NO_TRADE and proposal.opportunity_id is not None
                        and context.opportunities.get(proposal.symbol or "") != proposal.opportunity_id)
                    or (proposal.action in (Action.HOLD, Action.CLOSE, Action.MODIFY_STOP,
                                            Action.MODIFY_TARGET, Action.PARTIAL_CLOSE)
                        and proposal.parameters.position_ticket in position_links
                        and (position_links[proposal.parameters.position_ticket]["symbol"] != proposal.symbol
                             or position_links[proposal.parameters.position_ticket]["opportunity_id"]
                             != proposal.opportunity_id))):
                raise ValueError("identité ou opportunité de proposition incohérente")
        except Exception as exc:
            if isinstance(self.brain, ClassicBrainAdapter) and self.brain.last_response is not None:
                self.journal.log(rid, EventType.AGENT_RESPONSE,
                                 self.brain.last_response.model_dump(mode="json"))
                dec = self.brain.last_response.decision
                if dec is not None and dec.intent is not None and dec.intent.instrument not in shortlist:
                    reason = f"intent refusé : instrument {dec.intent.instrument} absent de la shortlist scannée"
                    self.journal.log(rid, EventType.INTENT_REJECTED_SCHEMA,
                                     {"agent": self.agent.name, "errors": [reason]})
                    return self._no_trade(scan, evaluated, self.agent.name, reason, shortlist)
            self.journal.log(rid, EventType.BRAIN_FAILURE,
                             {"source_id": self.brain.source_id, "reason": str(exc)})
            return self._no_trade(
                scan, evaluated, self.agent.name, f"réponse agent inexploitable : {exc}", shortlist,
            )
        self.journal.log(rid, EventType.ACTION_PROPOSAL, proposal.model_dump(mode="json"))
        if proposal.action is Action.NO_TRADE:
            return self._no_trade(
                scan, evaluated, self.agent.name,
                proposal.reasons[0] if proposal.reasons else "l'agent ne propose aucun trade",
                shortlist, proposal.proposal_id,
            )
        if proposal.action not in (Action.LONG, Action.SHORT):
            decision = self.execution.risk.evaluate_position_action(
                proposal, mode=self.run_mode, account_type=acct.account_type,
                positions=self.execution.my_positions(),
                kill_switch_active=self.execution.killswitch.is_active(),
                run_state=self.run.watchdog.run_state,
            )
            self.journal.log(rid, EventType.RISK_DECISION,
                             {"proposal_id": proposal.proposal_id, "opportunity_id": proposal.opportunity_id,
                              "action": proposal.action.value, "status": decision.status,
                              **decision.model_dump(mode="json"), "reason_lines": decision.reason_lines()})
            if decision.approved:
                self.journal.log(rid, EventType.POSITION_ACTION,
                                 {"proposal_id": proposal.proposal_id, "opportunity_id": proposal.opportunity_id,
                                  "position_ticket": proposal.parameters.position_ticket,
                                  "action": "HOLD", "status": "APPROVED"})
                return CycleOutcome(cycle=self._cycle, run_state=self.run.watchdog.run_state.value,
                                    decision="HOLD", reason="HOLD validé", shortlist=shortlist)
            self.journal.log(rid, EventType.POSITION_ACTION_REJECTED,
                             {"proposal_id": proposal.proposal_id, "reasons": decision.reason_lines()})
            return self._no_trade(scan, evaluated, self.agent.name, "; ".join(decision.reason_lines()), shortlist,
                                  proposal.proposal_id)

        # 6. validation avant le même TradeIntent / RiskEngine que le chemin historique.
        intent, problems = self._intent_from_proposal(proposal, shortlist)
        if intent is None:
            self.journal.log(
                rid,
                EventType.INTENT_REJECTED_SCHEMA,
                {"agent": self.agent.name, "proposal_id": proposal.proposal_id,
                 "errors": problems, "proposal": proposal.model_dump(mode="json")},
            )
            return self._no_trade(
                scan, evaluated, self.agent.name, f"intent refusé : {'; '.join(problems)}", shortlist,
                proposal.proposal_id,
            )

        # 6. exécution (ou dry-run ou paper)
        if self.run_mode is RunMode.PAPER and self.paper_engine is not None:
            # PAPER : risk validation via dry_run, puis execution simulee
            result = self.execution.submit(intent, dry_run=True)
            if result.status is ExecStatus.DRY_RUN_APPROVED and result.decision is not None:
                paper_pos = self.paper_engine.open_position(
                    intent, cycle_id, decision=result.decision,
                )
                self.journal.log(
                    rid,
                    EventType.POSITION_OPENED,
                    {"paper": True, **paper_pos.to_dict()},
                )
                from alladin.execution.models import ExecutionResult

                result = ExecutionResult(
                    status=ExecStatus.PAPER_EXECUTED,
                    intent=intent,
                    decision=result.decision,
                    messages=[f"position paper {paper_pos.paper_id} ouverte"],
                )
        else:
            result = self.execution.submit(intent, dry_run=not self.execute)

        self.monitor.sync()
        return CycleOutcome(
            cycle=self._cycle,
            run_state=self.run.watchdog.run_state.value,
            decision="TRADE"
            if result.status in (ExecStatus.EXECUTED, ExecStatus.DRY_RUN_APPROVED, ExecStatus.PAPER_EXECUTED)
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
        proposal_id: str | None = None,
    ) -> CycleOutcome:
        self.journal.no_trade(
            self.run.run_id,
            studied=sorted(set(scan.rejected) | set(shortlist)),
            candidates=shortlist,
            strategies_evaluated=evaluated,
            rejections=scan.rejected,
            agent=agent,
            reason=reason,
            proposal_id=proposal_id,
        )
        return CycleOutcome(
            cycle=self._cycle,
            run_state=self.run.watchdog.run_state.value,
            decision="NO_TRADE",
            reason=reason,
            shortlist=shortlist,
        )

    def _build_opportunities(self, scan: ScanReport, cycle_id: str) -> list[Opportunity]:
        """Convertit ScanCandidate -> Opportunity, journalise CREATED/REJECTED."""
        opportunities: list[Opportunity] = []
        rid = self.run.run_id

        # Candidats rejetés -> FILTERED
        for sym, reasons in scan.rejected.items():
            opp = Opportunity(
                opportunity_id=opportunity_identity(rid, cycle_id, sym),
                cycle_id=cycle_id,
                run_id=rid,
                symbol=sym,
                timeframe=self.scanner.primary,
                timestamp=scan.scanned_at,
                bid=0.0,
                ask=0.0,
                spread=0.0,
                rejection_reasons=reasons,
                status=OpportunityStatus.FILTERED,
            )
            self.journal.log(rid, EventType.OPPORTUNITY_REJECTED, opp.to_journal())
            opportunities.append(opp)

        # Candidats shortlistés -> QUALIFIED
        for cand in scan.candidates:
            opp = Opportunity(
                opportunity_id=opportunity_identity(rid, cycle_id, cand.symbol),
                cycle_id=cycle_id,
                run_id=rid,
                symbol=cand.symbol,
                timeframe=self.scanner.primary,
                timestamp=scan.scanned_at,
                bid=cand.tick.bid if cand.tick else 0.0,
                ask=cand.tick.ask if cand.tick else 0.0,
                spread=cand.tick.spread if cand.tick else 0.0,
                atr=cand.metrics.get("atr"),
                spread_atr_ratio=cand.spread_atr_ratio,
                regime=cand.regime,
                regime_confidence=cand.regime_confidence,
                session=cand.session,
                direction=cand.bias,
                strategy_candidates=list(cand.tf_trend.keys()) if cand.tf_trend else [],
                setup_score=cand.score,
                status=OpportunityStatus.QUALIFIED,
            )
            self.journal.log(rid, EventType.OPPORTUNITY_CREATED, opp.to_journal())
            opportunities.append(opp)

        return opportunities

    # ------------------------------------------------------------------ étapes

    def _signals(self, scan: ScanReport) -> tuple[list[tuple[TradeIntent, float]], dict[str, list[str]]]:
        out: list[tuple[TradeIntent, float]] = []
        evaluated: dict[str, list[str]] = {}
        now = self.broker.now()
        for cand in scan.candidates:
            decision, strategies = self.router.route(cand)
            self.journal.log(self.run.run_id, EventType.ROUTING, decision.model_dump(mode="json"))
            evaluated[cand.symbol] = decision.selected
            results: dict[str, str] = {}
            for strat in strategies:
                sig = strat.evaluate(StrategyContext(run_id=self.run.run_id, now=now, candidate=cand))
                results[f"{strat.id}@{strat.version}"] = "SIGNAL" if sig is not None else "NO_SETUP"
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
            self.journal.log(
                self.run.run_id,
                EventType.STRATEGY_EVAL,
                {
                    "symbol": cand.symbol,
                    "regime": cand.regime.value,
                    "results": results,
                    "skipped": decision.skipped,
                },
            )
        return out, evaluated

    def _context(self, scan: ScanReport, signals: list[tuple[TradeIntent, float]]) -> dict[str, Any]:
        acct = self.broker.account_info()
        wd = self.run.watchdog
        rules = self.run.profile.risk
        wc = sizing.working_capital(acct.equity, rules.working_capital_pct)
        owned = self.execution.my_positions()
        trades = {t.ticket: t for t in self.manager.repo.trades_for_run(self.run.run_id, "OPEN")
                  if t.ticket is not None}
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
                    {"ticket": p.ticket, "symbol": p.symbol, "side": p.side.value,
                     "profit": round(p.profit, 2),
                     "trade_id": trades[p.ticket].trade_id if p.ticket in trades else None,
                     "proposal_id": trades[p.ticket].proposal_id if p.ticket in trades else None,
                     "opportunity_id": trades[p.ticket].opportunity_id if p.ticket in trades else None}
                    for p in owned
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

    def _intent_from_proposal(
        self, proposal: ActionProposal, shortlist: list[str]
    ) -> tuple[TradeIntent | None, list[str]]:
        p = proposal.parameters
        problems: list[str] = []
        if p.requested_risk_pct_of_working_capital is None:
            problems.append("risque demandé absent")
        if proposal.symbol not in shortlist:
            problems.append(f"instrument {proposal.symbol} absent de la shortlist scannée")
        strat = self.router.registry.get(p.strategy_id or "")
        if strat is None:
            problems.append(f"stratégie {p.strategy_id} inconnue ou désactivée")
        elif strat.version != p.strategy_version:
            problems.append(f"version {p.strategy_version} != {strat.version} pour {p.strategy_id}")
        if problems:
            return None, problems
        try:
            return TradeIntent(
                intent_id=proposal.proposal_id, proposal_id=proposal.proposal_id,
                opportunity_id=proposal.opportunity_id, cycle_id=proposal.cycle_id,
                run_id=proposal.run_id,
                agent=proposal.source_id.removeprefix("classic:"),
                instrument=proposal.symbol or "", side=Side.BUY if proposal.action is Action.LONG else Side.SELL,
                strategy_id=p.strategy_id or "", strategy_version=p.strategy_version or "",
                market_regime=p.market_regime, entry_type=p.entry_type, entry=p.entry,
                stop_loss=p.stop_loss, take_profit=p.take_profit,
                requested_risk_pct_of_working_capital=p.requested_risk_pct_of_working_capital,
                confidence=proposal.confidence,
                reason="; ".join(proposal.reasons), sources=p.sources,
                created_at=proposal.timestamp, expires_at=proposal.timestamp + timedelta(minutes=15),
            ), []
        except (ValueError, ValidationError) as exc:
            return None, [str(exc)]

    # ------------------------------------------------------------------ boucle

    def run_loop(
        self,
        interval_s: float,
        max_cycles: int | None = None,
        on_cycle: Callable[[CycleOutcome], None] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        *,
        handle_signals: bool = True,
    ) -> None:
        """Boucle principale du daemon.

        handle_signals=True installe des gestionnaires SIGINT/SIGTERM qui
        permettent un arrêt propre : le cycle en cours se termine, puis la boucle
        s'arrête.  Ctrl+C depuis un cockpit séparé n'affecte pas le moteur.
        """
        self._stop_requested = False

        if handle_signals:
            _orig_int = signal.getsignal(signal.SIGINT)
            _orig_term = signal.getsignal(signal.SIGTERM)

            def _shutdown(signum: int, frame: object) -> None:
                self._stop_requested = True
                log.info("Signal %s reçu — arrêt propre après le cycle en cours.", signum)

            signal.signal(signal.SIGINT, _shutdown)
            signal.signal(signal.SIGTERM, _shutdown)

        self.journal.log(
            self.run.run_id,
            EventType.MODE_CHANGE,
            {"run_mode": self.run_mode.value, "interval_s": interval_s},
        )

        failures = 0
        n = 0
        try:
            while (max_cycles is None or n < max_cycles) and not self._stop_requested:
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
                if (max_cycles is None or n < max_cycles) and not self._stop_requested:
                    sleep(interval_s)
        finally:
            if handle_signals:
                signal.signal(signal.SIGINT, _orig_int)
                signal.signal(signal.SIGTERM, _orig_term)
            if self._stop_requested:
                log.info("Daemon arrêté proprement (signal).")
