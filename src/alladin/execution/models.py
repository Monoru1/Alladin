"""Modèles d'exécution et utilitaires d'identification des ordres ALLADIN."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ValidationError

from alladin.core.models import OrderCheck, OrderResult, TradeIntent
from alladin.risk.models import RiskDecision

COMMENT_PREFIX = "ALLADIN"
MT5_COMMENT_MAX = 31


def make_comment(run_id: str, strategy_id: str) -> str:
    """Ex. 'ALLADIN|RUN-001|TREND-01' (31 caractères max côté MT5)."""
    return f"{COMMENT_PREFIX}|{run_id}|{strategy_id}"[:MT5_COMMENT_MAX]


def parse_comment(comment: str) -> tuple[str, str] | None:
    parts = comment.split("|")
    if len(parts) >= 2 and parts[0] == COMMENT_PREFIX:
        return parts[1], parts[2] if len(parts) > 2 else ""
    return None


class ExecStatus(StrEnum):
    EXECUTED = "EXECUTED"
    DRY_RUN_APPROVED = "DRY_RUN_APPROVED"  # approuvé par le RiskEngine, volontairement non envoyé
    REJECTED_RISK = "REJECTED_RISK"
    REJECTED_BROKER = "REJECTED_BROKER"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class ExecutionResult(BaseModel):
    status: ExecStatus
    intent: TradeIntent
    decision: RiskDecision | None = None
    precheck: OrderCheck | None = None
    order: OrderResult | None = None
    messages: list[str] = []
    trade_id: str | None = None
    position_ticket: int | None = None

    @property
    def executed(self) -> bool:
        return self.status is ExecStatus.EXECUTED


class IntentParse(BaseModel):
    intent: TradeIntent | None = None
    errors: list[str] = []


def parse_intent(raw: dict[str, Any] | str, *, run_id: str, agent: str) -> IntentParse:
    """Validation de schéma d'une proposition brute (p. ex. sortie d'un LLM).

    `run_id` et `agent` sont imposés par l'orchestrateur : l'agent ne peut pas les choisir.
    Tout champ inconnu (notamment `volume`) est refusé.
    """
    try:
        data = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (ValueError, TypeError) as exc:
        return IntentParse(errors=[f"JSON invalide : {exc}"])
    data["run_id"] = run_id
    data["agent"] = agent
    try:
        return IntentParse(intent=TradeIntent.model_validate(data))
    except ValidationError as exc:
        return IntentParse(errors=[f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()])
