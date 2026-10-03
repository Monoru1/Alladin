"""Persist-before-send position actions. Ambiguous broker outcomes are never resent."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel
from sqlalchemy import Column, Index, MetaData, String, Table, Text
from sqlalchemy.exc import IntegrityError

from alladin.brain import Action, ActionProposal
from alladin.core.approval import issue_position_token
from alladin.core.enums import DealEntry, OrderAction, RunMode, Side
from alladin.core.models import OrderRequest, OwnedPosition
from alladin.journal.models import EventType
from alladin.journal.repository import paper_positions
from alladin.risk.models import RiskDecision
from alladin.risk.position import PositionActionContext

if TYPE_CHECKING:
    from alladin.execution.service import ExecutionService
    from alladin.market.paper import PaperExperimentEngine

_meta = MetaData()
actions = Table("position_actions", _meta,
                Column("proposal_id", String, primary_key=True), Column("run_id", String, nullable=False),
                Column("position_id", String, nullable=False), Column("mode", String, nullable=False),
                Column("fingerprint", String, nullable=False), Column("payload", Text, nullable=False),
                Column("status", String, nullable=False), Column("result", Text, nullable=True))
Index("one_pending_position_action", actions.c.run_id, actions.c.mode, actions.c.position_id,
      unique=True, sqlite_where=actions.c.status == "PENDING_CONFIRMATION",
      postgresql_where=actions.c.status == "PENDING_CONFIRMATION")


class PositionActionResult(BaseModel):
    proposal_id: str
    action: Action
    status: str
    messages: list[str] = []
    position_id: str | None = None
    duplicate: bool = False
    decision: RiskDecision | None = None

    @property
    def confirmed(self) -> bool:
        return self.status == "CONFIRMED"


class PositionActions:
    def __init__(self, service: ExecutionService) -> None:
        self.service = service
        self.repo = service.manager.repo
        _meta.create_all(self.repo.engine)

    def _row(self, proposal_id: str) -> dict[str, Any] | None:
        with self.repo.engine.connect() as c:
            row = c.execute(actions.select().where(actions.c.proposal_id == proposal_id,
                                                   actions.c.run_id == self.service.run.run_id)).mappings().first()
        return dict(row) if row else None

    def _finish(self, result: PositionActionResult) -> PositionActionResult:
        with self.repo.engine.begin() as c:
            c.execute(actions.update().where(actions.c.proposal_id == result.proposal_id,
                                             actions.c.run_id == self.service.run.run_id)
                      .values(status=result.status, result=result.model_dump_json()))
        self.service.journal.log(self.service.run.run_id, EventType.POSITION_ACTION,
                                 result.model_dump(mode="json"))
        return result

    def submit(self, proposal: ActionProposal, mode: RunMode,
               paper: PaperExperimentEngine | None = None) -> PositionActionResult:
        s, rid = self.service, self.service.run.run_id
        fingerprint = hashlib.sha256(proposal.model_dump_json().encode()).hexdigest()
        existing = self._row(proposal.proposal_id)
        if existing:
            if existing["fingerprint"] != fingerprint or existing["mode"] != mode.value:
                return PositionActionResult(proposal_id=proposal.proposal_id, action=proposal.action,
                                            status="BLOCKED", messages=["proposal_id réutilisé avec un contenu/mode différent"])
            result = (self.reconcile(existing, paper) if existing["status"] == "PENDING_CONFIRMATION"
                      else PositionActionResult.model_validate_json(existing["result"]))
            return result.model_copy(update={"duplicate": True})
        if proposal.run_id != rid:
            return PositionActionResult(proposal_id=proposal.proposal_id, action=proposal.action,
                                        status="BLOCKED", messages=["run incohérent"])
        views = s.owned_positions(mode, paper)
        p = proposal.parameters
        pos = next((v for v in views if (p.position_id == v.position_id if p.position_id is not None
                                        else p.position_ticket == v.broker_ticket)), None)
        if pos is None:
            result = PositionActionResult(proposal_id=proposal.proposal_id, action=proposal.action,
                                          status="REJECTED_RISK", messages=["position absente ou non possédée"])
            s.journal.log(rid, EventType.POSITION_ACTION_REJECTED, result.model_dump(mode="json"))
            return result
        account = s.broker.account_info()
        s.assert_account_binding(account)
        s.manager.sync_watchdog(s.run, account, len(views))
        spec, tick = s.broker.symbol_spec(pos.symbol), s.broker.tick(pos.symbol)
        if spec is None or tick is None:
            return PositionActionResult(proposal_id=proposal.proposal_id, action=proposal.action,
                                        status="BLOCKED", messages=["données de gestion indisponibles"])
        ctx = PositionActionContext(workspace=s.run.workspace, run_id=rid, mode=mode, account_type=account.account_type,
                                    run_state=s.run.watchdog.run_state,
                                    kill_switch_active=s.killswitch.is_active(), now=s.clock(), observed_at=s.clock(),
                                    position=pos, spec=spec, tick=tick, capabilities=s.broker.capabilities(),
                                    trade_allowed=account.trade_allowed)
        decision = s.risk.plan_position_action(proposal, ctx)
        s.journal.log(rid, EventType.RISK_DECISION, {"action": proposal.action.value,
                      "proposal_id": proposal.proposal_id, "opportunity_id": proposal.opportunity_id,
                      "status": decision.status, **decision.model_dump(mode="json")})
        if not decision.approved:
            result = PositionActionResult(proposal_id=proposal.proposal_id, action=proposal.action,
                                          status="REJECTED_RISK", position_id=pos.position_id,
                                          decision=decision, messages=decision.reason_lines())
            s.journal.log(rid, EventType.POSITION_ACTION_REJECTED, result.model_dump(mode="json"))
            return result
        request = OrderRequest(action=OrderAction.MODIFY if proposal.action in (Action.MODIFY_STOP, Action.MODIFY_TARGET)
                               else OrderAction.CLOSE, symbol=pos.symbol,
                               side=pos.side if proposal.action in (Action.MODIFY_STOP, Action.MODIFY_TARGET)
                               else pos.side.opposite, volume=decision.volume,
                               stop_loss=decision.stop_loss, take_profit=decision.take_profit,
                               position_ticket=pos.broker_ticket, magic=s.run.magic,
                               comment=s.owned_broker_comment(pos.broker_ticket), deviation_points=s.deviation)
        payload: dict[str, Any] = {"proposal": proposal.model_dump(mode="json"),
                                   "before": pos.model_dump(mode="json"), "request": request.model_dump(mode="json"),
                                   "decision": decision.model_dump(mode="json"), "claimed_at": s.clock().isoformat()}
        if mode is RunMode.DEMO and proposal.action in (Action.CLOSE, Action.PARTIAL_CLOSE):
            payload["known_deals"] = [d.ticket for d in s.broker.history_deals(s.clock() - timedelta(days=1), s.clock())]
        try:
            with self.repo.engine.begin() as c:
                c.execute(actions.insert().values(proposal_id=proposal.proposal_id, run_id=rid,
                          position_id=pos.position_id, mode=mode.value, fingerprint=fingerprint,
                          payload=json.dumps(payload), status="PENDING_CONFIRMATION"))
        except IntegrityError:
            return PositionActionResult(proposal_id=proposal.proposal_id, action=proposal.action,
                                        status="BLOCKED", messages=["action concurrente ou non confirmée sur cette position"])
        s.journal.log(rid, EventType.POSITION_ACTION, {
            "proposal_id": proposal.proposal_id, "position_id": pos.position_id,
            "action": proposal.action.value, "status": "PENDING_CONFIRMATION", "stage": "CLAIMED",
        })
        if proposal.action is Action.HOLD:
            return self._finish(PositionActionResult(proposal_id=proposal.proposal_id, action=proposal.action,
                                                     status="CONFIRMED", position_id=pos.position_id, decision=decision))
        row = self._row(proposal.proposal_id)
        assert row is not None
        if mode is RunMode.PAPER:
            assert paper is not None
            return self._paper(row, paper)
        try:
            # Recheck the kill switch immediately before the only broker sending path.
            if s.killswitch.is_active():
                return self._finish(PositionActionResult(proposal_id=proposal.proposal_id, action=proposal.action,
                                                         status="BLOCKED", messages=["kill switch actif avant envoi"]))
            check = s.broker.check_order(request)
            s.journal.log(rid, EventType.ORDER_PRECHECK, {"proposal_id": proposal.proposal_id,
                          "request": request.model_dump(mode="json"), "check": check.model_dump(mode="json")})
            if not check.ok:
                return self._finish(PositionActionResult(proposal_id=proposal.proposal_id, action=proposal.action,
                                                         status="REJECTED_BROKER", messages=[check.message]))
            fresh = next((v for v in s.owned_positions(mode) if v.position_id == pos.position_id), None)
            fresh_tick = s.broker.tick(pos.symbol)
            if fresh != pos or fresh_tick is None or s.killswitch.is_active():
                return self._finish(PositionActionResult(proposal_id=proposal.proposal_id, action=proposal.action,
                                                         status="BLOCKED", messages=["position ou kill switch changé avant envoi"]))
            refreshed = ctx.model_copy(update={"now": s.clock(), "observed_at": s.clock(), "tick": fresh_tick,
                                               "run_state": s.run.watchdog.run_state})
            if not s.risk.plan_position_action(proposal, refreshed).approved:
                return self._finish(PositionActionResult(proposal_id=proposal.proposal_id, action=proposal.action,
                                                         status="BLOCKED", messages=["risque changé avant envoi"]))
            s.assert_account_binding(s.broker.assert_demo())
            token = issue_position_token(rid, "MODIFY" if request.action is OrderAction.MODIFY else "CLOSE", proposal.proposal_id,
                                         request.symbol, request.volume, request=request)
            s.journal.log(rid, EventType.ORDER_SENT, {"proposal_id": proposal.proposal_id, **request.model_dump(mode="json")})
            response = s.broker.send_order(request, token)
            s.journal.log(rid, EventType.ORDER_RESULT, {"proposal_id": proposal.proposal_id, **response.model_dump(mode="json")})
            if not response.accepted and response.retcode > 0:
                return self._finish(PositionActionResult(proposal_id=proposal.proposal_id, action=proposal.action,
                                                         status="REJECTED_BROKER", messages=[response.message]))
        except Exception as exc:
            s.journal.log(rid, EventType.INFO, {"proposal_id": proposal.proposal_id,
                          "alert": "envoi ambigu : réconciliation requise, aucun retry", "reason": str(exc)})
        return self.reconcile(row, paper)

    def reconcile(self, row: dict[str, Any], paper: PaperExperimentEngine | None = None) -> PositionActionResult:
        payload = json.loads(row["payload"])
        proposal = ActionProposal.model_validate(payload["proposal"])
        pos = OwnedPosition.model_validate(payload["before"])
        result = PositionActionResult(proposal_id=proposal.proposal_id, action=proposal.action,
                                      position_id=pos.position_id, status="PENDING_CONFIRMATION")
        if row["mode"] == RunMode.PAPER.value:
            # PAPER transaction commits mutation and confirmation together. Never replay a claim.
            return result
        try:
            current = next((p for p in self.service.my_positions() if p.ticket == pos.broker_ticket), None)
            req = OrderRequest.model_validate(payload["request"])
            if proposal.action in (Action.MODIFY_STOP, Action.MODIFY_TARGET):
                confirmed = (current is not None and current.symbol == pos.symbol and current.side is pos.side
                             and abs(current.volume - pos.remaining_volume) < 1e-9
                             and current.sl == req.stop_loss and current.tp == req.take_profit)
            else:
                remaining = pos.remaining_volume - req.volume
                volume_ok = ((current is None and remaining < 1e-9) or
                             (current is not None and current.symbol == pos.symbol and current.side is pos.side
                              and abs(current.volume - remaining) < 1e-9
                              and current.sl == pos.stop_loss and current.tp == pos.take_profit))
                since = datetime.fromisoformat(payload["claimed_at"]) - timedelta(minutes=5)
                deals = self.service.broker.history_deals(since, self.service.clock() + timedelta(minutes=5))
                new = [d for d in deals if d.ticket not in payload.get("known_deals", [])
                       and d.position_id == pos.broker_ticket and d.symbol == pos.symbol
                       and d.magic == self.service.run.magic and d.entry in (DealEntry.OUT, DealEntry.OUT_BY)]
                confirmed = volume_ok and abs(sum(d.volume for d in new) - req.volume) < 1e-9
            if confirmed:
                return self._finish(result.model_copy(update={"status": "CONFIRMED"}))
        except Exception as exc:
            result.messages = [f"réconciliation indisponible : {exc}"]
        return result

    def reconcile_pending(self, paper: PaperExperimentEngine | None = None) -> list[PositionActionResult]:
        with self.repo.engine.connect() as c:
            rows = c.execute(actions.select().where(actions.c.run_id == self.service.run.run_id,
                                                    actions.c.status == "PENDING_CONFIRMATION")).mappings().all()
        return [self.reconcile(dict(r), paper) for r in rows]

    def _paper(self, row: dict[str, Any], paper: PaperExperimentEngine) -> PositionActionResult:
        payload = json.loads(row["payload"])
        proposal = ActionProposal.model_validate(payload["proposal"])
        before = OwnedPosition.model_validate(payload["before"])
        decision = RiskDecision.model_validate(payload["decision"])
        source = next(p for p in paper.open_positions() if p.paper_id == before.paper_id)
        pos = replace(source, intent=dict(source.intent))
        if proposal.action is Action.MODIFY_STOP:
            assert decision.stop_loss is not None
            pos.sl = decision.stop_loss
        elif proposal.action is Action.MODIFY_TARGET:
            pos.tp = decision.take_profit
        else:
            tick = self.service.broker.tick(pos.symbol)
            spec = self.service.broker.symbol_spec(pos.symbol)
            if tick is None or spec is None:
                return PositionActionResult(proposal_id=proposal.proposal_id, action=proposal.action,
                                            status="PENDING_CONFIRMATION", messages=["tick PAPER indisponible"])
            price = tick.bid if pos.side is Side.BUY else tick.ask
            if proposal.action is Action.CLOSE:
                pos.close(price, "CLOSED_MANUAL", self.service.clock(), spec.point)
            paper.realize(pos, price, decision.volume)
            if proposal.action is Action.PARTIAL_CLOSE:
                pos.volume -= decision.volume
        result = PositionActionResult(proposal_id=proposal.proposal_id, action=proposal.action,
                                      status="CONFIRMED", position_id=before.position_id, decision=decision)
        fields = pos.to_persistence()
        with self.repo.engine.begin() as c:
            updated = c.execute(paper_positions.update().where(paper_positions.c.paper_id == before.paper_id,
                                paper_positions.c.run_id == self.service.run.run_id,
                                paper_positions.c.status == "OPEN", paper_positions.c.volume == before.remaining_volume,
                                paper_positions.c.sl == before.stop_loss, paper_positions.c.tp == before.take_profit,
                                paper_positions.c.workspace == self.repo.workspace.value)
                                .values(**fields))
            if updated.rowcount != 1:
                raise ValueError("position PAPER modifiée concurremment : transaction annulée")
            c.execute(actions.update().where(actions.c.proposal_id == proposal.proposal_id)
                      .values(status="CONFIRMED", result=result.model_dump_json()))
        paper.restore()
        self.service.journal.log(self.service.run.run_id, EventType.POSITION_ACTION,
                                 {**result.model_dump(mode="json"), "paper": True,
                                  "realized_pnl": pos.realized_pnl, "remaining_volume": pos.volume})
        return result
