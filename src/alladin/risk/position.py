"""Deterministic, effect-free policy for management of an owned position.

Approval is a plan, not a fill or a broker token. Execution must refresh ownership,
bind the exact request, persist an idempotency claim and confirm the resulting state.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal

from pydantic import BaseModel, ConfigDict, ValidationError

from alladin.brain import Action, ActionProposal
from alladin.brokers.base import BrokerCapabilities
from alladin.core.enums import AccountType, RunMode, RunState, Side
from alladin.core.models import InstrumentSpec, OwnedPosition, Tick
from alladin.risk.models import RejectCode, RiskDecision, RiskReason

MAX_CONTEXT_AGE = timedelta(seconds=60)


class PositionActionContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    mode: RunMode
    account_type: AccountType
    run_state: RunState
    kill_switch_active: bool = False
    now: datetime
    observed_at: datetime
    position: OwnedPosition
    spec: InstrumentSpec
    tick: Tick
    capabilities: BrokerCapabilities
    trade_allowed: bool = True
    # A blocked challenge never legitimises increasing exposure. All plans here
    # either preserve or reduce it; protective exits remain a separate pathway.
    challenge_blocked: bool = False


def evaluate_position_action(proposal: ActionProposal, ctx: PositionActionContext) -> RiskDecision:
    try:
        proposal = ActionProposal.model_validate(proposal.model_dump())
    except ValidationError:
        return RiskDecision(intent_id=proposal.proposal_id, approved=False, reasons=[
            RiskReason(code=RejectCode.POSITION_ACTION_UNSUPPORTED, message="schéma de proposition de gestion invalide")])
    reasons: list[RiskReason] = []

    def reject(code: RejectCode, message: str) -> None:
        reasons.append(RiskReason(code=code, message=message))

    pos, spec, tick, p = ctx.position, ctx.spec, ctx.tick, proposal.parameters
    management = (Action.HOLD, Action.CLOSE, Action.MODIFY_STOP, Action.MODIFY_TARGET, Action.PARTIAL_CLOSE)
    if proposal.action not in management:
        reject(RejectCode.POSITION_ACTION_UNSUPPORTED, "action hors gestion de position")
    if (proposal.run_id != ctx.run_id or pos.run_id != ctx.run_id):
        reject(RejectCode.RUN_MISMATCH, "position/proposition/contexte de runs différents")
    if (pos.status != "OPEN" or pos.symbol != proposal.symbol
            or (p.position_id is not None and p.position_id != pos.position_id)
            or (p.position_ticket is not None and p.position_ticket != pos.broker_ticket)
            or proposal.opportunity_id != pos.opportunity_id):
        reject(RejectCode.POSITION_NOT_OWNED, "identité ou lien causal de position incohérent")
    if (ctx.mode not in (RunMode.DEMO, RunMode.PAPER) or pos.mode != ctx.mode
            or ctx.account_type is not AccountType.DEMO
            or (ctx.mode is RunMode.DEMO and (pos.broker_ticket is None or pos.paper_id is not None))
            or (ctx.mode is RunMode.PAPER and (pos.paper_id is None or pos.broker_ticket is not None))):
        reject(RejectCode.MODE_SAFETY, "position/mode/compte incompatible avec DEMO ou PAPER isolé")
    if ctx.kill_switch_active or ctx.run_state not in (RunState.RUNNING, RunState.TARGET_REACHED):
        reject(RejectCode.KILL_SWITCH, "gestion Brain bloquée par kill switch ou état terminal")
    if not ctx.trade_allowed and ctx.mode is RunMode.DEMO and proposal.action is not Action.HOLD:
        reject(RejectCode.TRADE_NOT_ALLOWED, "compte DEMO non autorisé à trader")
    times = (ctx.now, ctx.observed_at, tick.time, proposal.timestamp)
    if any(t.tzinfo is None for t in times):
        reject(RejectCode.EXPIRED, "horodatages de gestion sans fuseau")
    elif any(not timedelta(0) <= ctx.now - t <= MAX_CONTEXT_AGE for t in times[1:]):
        reject(RejectCode.EXPIRED, "contexte, tick ou proposition périmé/futur")
    if spec.symbol != pos.symbol or tick.symbol != pos.symbol:
        reject(RejectCode.INSTRUMENT_MISMATCH, "spec/tick différent du symbole de la position")

    positive = (pos.original_volume, pos.remaining_volume, pos.entry_price,
                spec.point, spec.trade_tick_size, spec.volume_min, spec.volume_max, spec.volume_step,
                tick.bid, tick.ask)
    optional = (pos.stop_loss, pos.take_profit)
    valid_numbers = (all(math.isfinite(v) and v > 0 for v in positive)
                     and all(v is None or (math.isfinite(v) and v > 0) for v in optional)
                     and math.isfinite(spec.stops_level) and spec.stops_level >= 0
                     and math.isfinite(spec.freeze_level) and spec.freeze_level >= 0
                     and tick.ask >= tick.bid and spec.volume_max >= spec.volume_min
                     and pos.remaining_volume <= pos.original_volume + 1e-9)
    if not valid_numbers:
        reject(RejectCode.BAD_GEOMETRY, "données de position/marché/contrat non finies ou incohérentes")
    if ctx.mode is RunMode.DEMO and proposal.action is not Action.HOLD:
        cap = {Action.CLOSE: ctx.capabilities.can_close_position,
               Action.PARTIAL_CLOSE: ctx.capabilities.can_partial_close,
               Action.MODIFY_STOP: ctx.capabilities.can_modify_stop,
               Action.MODIFY_TARGET: ctx.capabilities.can_modify_target}.get(proposal.action, False)
        if not cap or not ctx.capabilities.reliable_position_reconciliation:
            reject(RejectCode.POSITION_ACTION_UNSUPPORTED, "capacité d'action ou réconciliation absente")

    volume = pos.remaining_volume
    sl, tp = pos.stop_loss, pos.take_profit
    if valid_numbers:
        price = tick.bid if pos.side is Side.BUY else tick.ask
        minimum = spec.stops_level * spec.point
        frozen = spec.freeze_level * spec.point
        if proposal.action in (Action.MODIFY_STOP, Action.MODIFY_TARGET):
            value = p.stop_loss if proposal.action is Action.MODIFY_STOP else p.take_profit
            assert value is not None  # validated ActionProposal contract
            steps = value / spec.trade_tick_size
            if not math.isfinite(steps) or abs(steps - round(steps)) > 1e-6:
                reject(RejectCode.BAD_GEOMETRY, "prix hors grille tick broker")
            if sl is None:
                reject(RejectCode.NO_STOP_LOSS, "modification interdite sur position non protégée")
            if any(v is not None and abs(price - v) <= frozen + 1e-12 for v in (sl, tp)) and frozen > 0:
                reject(RejectCode.STOPS_TOO_CLOSE, "protection existante dans la zone freeze broker")
            is_stop = proposal.action is Action.MODIFY_STOP
            correct_side = ((value < price if pos.side is Side.BUY else value > price) if is_stop
                            else (value > price if pos.side is Side.BUY else value < price))
            if not correct_side:
                reject(RejectCode.BAD_GEOMETRY, "protection du mauvais côté du prix exécutable")
            if abs(price - value) < minimum - 1e-12 or (frozen > 0 and abs(price - value) <= frozen + 1e-12):
                reject(RejectCode.STOPS_TOO_CLOSE, "nouvelle protection dans la zone stops/freeze broker")
            if is_stop:
                if sl is not None and ((pos.side is Side.BUY and value < sl - 1e-12)
                                       or (pos.side is Side.SELL and value > sl + 1e-12)):
                    reject(RejectCode.RISK_EXCEEDS_CAP, "élargissement du stop interdit : risque accru")
                sl = value
            else:
                tp = value
        elif proposal.action is Action.PARTIAL_CLOSE:
            assert p.partial_fraction is not None
            if p.partial_fraction >= 1:
                reject(RejectCode.SIZING, "fraction 1 interdite : utiliser CLOSE explicitement")
            # Strict floor on decimal inputs: never close more than requested.
            step = Decimal(str(spec.volume_step))
            raw = Decimal(str(pos.remaining_volume)) * Decimal(str(p.partial_fraction))
            volume = float((raw / step).to_integral_value(rounding=ROUND_DOWN) * step)
            remaining = pos.remaining_volume - volume
            if volume < spec.volume_min - 1e-9 or remaining < spec.volume_min - 1e-9:
                reject(RejectCode.VOLUME_BELOW_MIN, "fermeture ou reliquat sous minimum broker")
            steps = remaining / spec.volume_step
            if not math.isfinite(steps) or abs(steps - round(steps)) > 1e-6:
                reject(RejectCode.SIZING, "reliquat hors pas broker")
        if proposal.action in (Action.CLOSE, Action.PARTIAL_CLOSE):
            steps = volume / spec.volume_step
            if (not math.isfinite(steps) or abs(steps - round(steps)) > 1e-6
                    or not spec.volume_min - 1e-9 <= volume <= spec.volume_max + 1e-9):
                reject(RejectCode.SIZING, "volume de fermeture hors contrat broker")

    return RiskDecision(intent_id=proposal.proposal_id, approved=not reasons, reasons=reasons,
                        volume=volume if not reasons and proposal.action is not Action.HOLD else 0,
                        stop_loss=sl, take_profit=tp)
