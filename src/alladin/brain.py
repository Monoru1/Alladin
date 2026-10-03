"""Contrat de décision indépendant du broker et adaptateur du chemin classique."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from alladin.agents.base import AgentAdapter, AgentRequest, AgentResponse
from alladin.core.enums import DecisionKind, EntryType, MarketRegime


class Action(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    NO_TRADE = "NO_TRADE"
    HOLD = "HOLD"
    CLOSE = "CLOSE"
    MODIFY_STOP = "MODIFY_STOP"
    MODIFY_TARGET = "MODIFY_TARGET"
    PARTIAL_CLOSE = "PARTIAL_CLOSE"


class ProposalParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy_id: str | None = None
    strategy_version: str | None = None
    market_regime: MarketRegime = MarketRegime.UNKNOWN
    entry_type: EntryType = EntryType.MARKET
    entry: float | None = Field(default=None, strict=True, allow_inf_nan=False, gt=0)
    stop_loss: float | None = Field(default=None, strict=True, allow_inf_nan=False, gt=0)
    take_profit: float | None = Field(default=None, strict=True, allow_inf_nan=False, gt=0)
    requested_risk_pct_of_working_capital: float | None = Field(
        default=None, strict=True, allow_inf_nan=False, gt=0, le=100
    )
    position_ticket: int | None = Field(default=None, strict=True, gt=0)
    partial_fraction: float | None = Field(default=None, strict=True, allow_inf_nan=False, gt=0, le=1)
    sources: tuple[str, ...] = ()


def proposal_identity(run_id: str, cycle_id: str, opportunity_id: str | None,
                      source_id: str, source_version: str = "1") -> str:
    """Une seule décision par source/opportunité/cycle ; même input => même identité."""
    key = f"alladin:proposal:v1:{run_id}:{cycle_id}:{opportunity_id or '-'}:{source_id}:{source_version}"
    return f"AP-{uuid5(NAMESPACE_URL, key).hex}"


class ActionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(default=1, strict=True)
    proposal_id: str
    source_id: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    cycle_id: str = Field(min_length=1)
    opportunity_id: str | None = None
    symbol: str | None = None
    action: Action
    confidence: float | None = Field(default=None, strict=True, allow_inf_nan=False, ge=0, le=1)
    reasons: tuple[str, ...] = ()
    timestamp: datetime
    parameters: ProposalParameters = Field(default_factory=ProposalParameters)

    @model_validator(mode="after")
    def validate_contract(self) -> ActionProposal:
        if self.schema_version != 1:
            raise ValueError("version ActionProposal non supportée")
        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp UTC requis")
        expected = proposal_identity(self.run_id, self.cycle_id, self.opportunity_id,
                                     self.source_id, self.source_version)
        if self.proposal_id != expected:
            raise ValueError("proposal_id incohérent")
        entry = self.action in (Action.LONG, Action.SHORT)
        management = self.action in (Action.HOLD, Action.CLOSE, Action.MODIFY_STOP,
                                     Action.MODIFY_TARGET, Action.PARTIAL_CLOSE)
        p = self.parameters
        if (entry or management) and (not self.symbol or not self.opportunity_id):
            raise ValueError("symbole et opportunité requis pour une action de marché")
        if entry:
            if not p.strategy_id or not p.strategy_version or p.requested_risk_pct_of_working_capital is None:
                raise ValueError("paramètres de stratégie et risque requis pour une entrée")
            if p.position_ticket is not None or p.partial_fraction is not None:
                raise ValueError("paramètres de position interdits pour une entrée")
            if p.entry_type is not EntryType.MARKET and p.entry is None:
                raise ValueError("prix requis pour LIMIT/STOP")
            if p.entry is not None:
                if p.stop_loss is not None and ((self.action is Action.LONG and p.stop_loss >= p.entry)
                                               or (self.action is Action.SHORT and p.stop_loss <= p.entry)):
                    raise ValueError("stop contradictoire avec le sens d'entrée")
                if p.take_profit is not None and ((self.action is Action.LONG and p.take_profit <= p.entry)
                                                 or (self.action is Action.SHORT and p.take_profit >= p.entry)):
                    raise ValueError("target contradictoire avec le sens d'entrée")
        elif management:
            if p.position_ticket is None:
                raise ValueError("position_ticket requis")
            if self.action is Action.MODIFY_STOP and p.stop_loss is None:
                raise ValueError("stop_loss requis")
            if self.action is Action.MODIFY_TARGET and p.take_profit is None:
                raise ValueError("take_profit requis")
            if self.action is Action.PARTIAL_CLOSE and p.partial_fraction is None:
                raise ValueError("partial_fraction requis")
            if p.entry is not None or p.requested_risk_pct_of_working_capital is not None:
                raise ValueError("paramètres d'entrée interdits pour une gestion")
            if p.strategy_id is not None or p.strategy_version is not None or p.entry_type is not EntryType.MARKET:
                raise ValueError("paramètres de stratégie interdits pour une gestion")
            if self.action in (Action.HOLD, Action.CLOSE) and (p.stop_loss is not None or p.take_profit is not None
                                                               or p.partial_fraction is not None):
                raise ValueError("paramètres de modification interdits")
            if self.action is Action.MODIFY_STOP and (p.take_profit is not None or p.partial_fraction is not None):
                raise ValueError("paramètres incompatibles avec MODIFY_STOP")
            if self.action is Action.MODIFY_TARGET and (p.stop_loss is not None or p.partial_fraction is not None):
                raise ValueError("paramètres incompatibles avec MODIFY_TARGET")
            if self.action is Action.PARTIAL_CLOSE and (p.stop_loss is not None or p.take_profit is not None):
                raise ValueError("paramètres incompatibles avec PARTIAL_CLOSE")
        elif p != ProposalParameters():
            raise ValueError("NO_TRADE ne porte aucun paramètre d'ordre")
        return self


class BrainContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    cycle_id: str
    timestamp: datetime
    opportunities: dict[str, str]  # symbol -> ID qualifié
    market: dict[str, Any]  # snapshot sans broker ni secrets

    @field_validator("market")
    @classmethod
    def serializable_snapshot(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            json.dumps(value, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("contexte Brain non sérialisable") from exc
        return value


class Brain(Protocol):
    source_id: str
    source_version: str

    def decide(self, context: BrainContext) -> ActionProposal: ...


class ClassicBrainAdapter:
    """Préserve exactement la sélection AgentAdapter; traduit seulement sa décision."""

    source_version = "classic-1"

    def __init__(self, agent: AgentAdapter) -> None:
        self.agent = agent
        self.source_id = f"classic:{agent.name}"
        self.last_response: AgentResponse | None = None

    def decide(self, context: BrainContext) -> ActionProposal:
        self.last_response = None
        response = self.agent.propose(AgentRequest(run_id=context.run_id, context=context.market))
        self.last_response = response
        if not response.ok or response.decision is None:
            raise ValueError(f"réponse agent inexploitable : {'; '.join(response.errors)}")
        dec = response.decision
        if dec.decision is DecisionKind.NO_TRADE:
            if dec.intent is not None:
                raise ValueError("NO_TRADE avec intent contradictoire")
            action, symbol, opp, params = Action.NO_TRADE, None, None, ProposalParameters()
            confidence = None
        else:
            if dec.intent is None:
                raise ValueError("TRADE sans intent")
            draft = dec.intent
            action = Action.LONG if draft.side.value == "BUY" else Action.SHORT
            symbol = draft.instrument
            opp = context.opportunities.get(symbol)
            params = ProposalParameters(
                strategy_id=draft.strategy_id, strategy_version=draft.strategy_version,
                market_regime=draft.market_regime, entry_type=draft.entry_type, entry=draft.entry,
                stop_loss=draft.stop_loss, take_profit=draft.take_profit,
                requested_risk_pct_of_working_capital=draft.requested_risk_pct_of_working_capital,
                sources=draft.sources,
            )
            confidence = draft.confidence
        return ActionProposal(
            proposal_id=proposal_identity(context.run_id, context.cycle_id, opp,
                                          self.source_id, self.source_version),
            source_id=self.source_id, source_version=self.source_version,
            run_id=context.run_id, cycle_id=context.cycle_id, opportunity_id=opp,
            symbol=symbol, action=action, confidence=confidence,
            reasons=[dec.reason or "l'agent ne propose aucun trade"] if action is Action.NO_TRADE else
                    [r for r in (dec.reason, dec.intent.reason if dec.intent else "") if r],
            timestamp=context.timestamp.astimezone(UTC), parameters=params,
        )
