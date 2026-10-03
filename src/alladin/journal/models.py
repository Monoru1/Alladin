"""Modèles du journal d'audit."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from alladin.core.workspace import AccountBinding, WorkspaceId


class EventType(StrEnum):
    RUN_CREATED = "run.created"
    RUN_STATE = "run.state"
    UNIVERSE = "market.universe"
    SCAN = "market.scan"
    ROUTING = "strategy.routing"
    SIGNAL = "strategy.signal"
    STRATEGY_EVAL = "strategy.evaluation"
    CYCLE_START = "cycle.start"
    CYCLE_END = "cycle.end"
    AGENT_REQUEST = "agent.request"
    AGENT_RESPONSE = "agent.response"
    NO_TRADE = "decision.no_trade"
    TRADE_INTENT = "decision.trade_intent"
    INTENT_REJECTED_SCHEMA = "decision.intent_invalid"
    RISK_DECISION = "risk.decision"
    ORDER_PRECHECK = "order.precheck"
    ORDER_SENT = "order.sent"
    ORDER_RESULT = "order.result"
    EXECUTION_BLOCKED = "execution.blocked"
    POSITION_OPENED = "position.opened"
    POSITION_UPDATE = "position.update"
    POSITION_CLOSED = "position.closed"
    WATCHDOG = "watchdog.event"
    ACCOUNT_SNAPSHOT = "account.snapshot"
    KILL_SWITCH = "kill_switch"
    RECONCILE = "reconcile"
    INFO = "info"
    OPPORTUNITY_CREATED = "opportunity.created"
    OPPORTUNITY_REJECTED = "opportunity.rejected"
    ACTION_PROPOSAL = "decision.action_proposal"
    BRAIN_FAILURE = "decision.brain_failure"
    POSITION_ACTION_REJECTED = "position.action_rejected"
    POSITION_ACTION = "position.action"
    MODE_CHANGE = "mode.change"
    OUTCOME = "learning.outcome"


class JournalEvent(BaseModel):
    workspace: WorkspaceId = WorkspaceId.ALLADIN
    id: int
    run_id: str
    seq: int
    ts: datetime
    type: str
    payload: dict[str, Any]
    hash: str
    cycle_id: str | None = None


class RunRecord(BaseModel):
    workspace: WorkspaceId = WorkspaceId.ALLADIN
    account_binding: AccountBinding | None = None
    run_id: str
    seq: int
    profile_id: str
    state: str
    phase: int
    initial_balance: float
    broker: str
    account: str
    magic: int
    kind: str = "RUN"
    created_at: datetime
    updated_at: datetime
    watchdog_state: dict[str, Any]


class TradeRecord(BaseModel):
    workspace: WorkspaceId = WorkspaceId.ALLADIN
    trade_id: str
    proposal_id: str | None = None
    opportunity_id: str | None = None
    run_id: str
    symbol: str
    side: str
    strategy_id: str
    strategy_version: str
    regime: str
    agent: str
    status: str
    ticket: int | None = None
    volume: float
    entry_requested: float | None = None
    entry_executed: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    risk_amount: float
    risk_pct_of_wc: float
    spread_at_entry: float | None = None
    slippage: float | None = None
    opened_at: datetime
    closed_at: datetime | None = None
    close_price: float | None = None
    close_reason: str | None = None
    pnl_gross: float | None = None
    commission: float | None = None
    swap: float | None = None
    net_pnl: float | None = None
    r_multiple: float | None = None
    mae: float = 0.0  # pire perte flottante observée (<= 0), devise du compte
    mfe: float = 0.0  # meilleur gain flottant observé (>= 0)
    equity_after: float | None = None
    cycle_id: str | None = None
    account_currency: str | None = None
    price_value_per_lot: float | None = None  # frozen opening conversion, modeled counterfactual only
    excursion_samples: int = 0
    adopted: bool = False  # position retrouvée à la réconciliation sans enregistrement préalable
