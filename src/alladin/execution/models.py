"""Modèles d'exécution et utilitaires d'identification des ordres ALLADIN."""

from __future__ import annotations

import json
import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ValidationError

from alladin.core.models import OrderCheck, OrderResult, TradeIntent
from alladin.risk.models import RiskDecision

COMMENT_PREFIX = "ALD"
MT5_COMMENT_MAX = 31
_COMMENT_RE = re.compile(r"^ALD-([RS])-([0-9]{1,20})$")


def make_comment(run_id: str, magic: int) -> str:
    """Identifiant MT5 court : le magic est la clé, le commentaire confirme le type de run."""
    kind = "S" if run_id.startswith("SYSTEM-TEST-") else "R" if run_id.startswith("RUN-") else None
    if kind is None or not 0 <= magic < 2**64:
        raise ValueError("run_id ou magic invalide pour le commentaire MT5")
    comment = f"{COMMENT_PREFIX}-{kind}-{magic}"
    if len(comment) > MT5_COMMENT_MAX or not comment.isascii():
        raise ValueError("commentaire MT5 trop long ou non ASCII")
    return comment


def parse_comment(comment: str) -> tuple[str, int] | None:
    match = _COMMENT_RE.fullmatch(comment)
    if match is None:
        return None
    return ("SYSTEM-TEST" if match[1] == "S" else "RUN", int(match[2]))


def comment_matches(comment: str, run_id: str, magic: int) -> bool:
    parsed = parse_comment(comment)
    expected_kind = "SYSTEM-TEST" if run_id.startswith("SYSTEM-TEST-") else "RUN"
    return parsed == (expected_kind, magic)


class ExecStatus(StrEnum):
    EXECUTED = "EXECUTED"
    PAPER_EXECUTED = "PAPER_EXECUTED"  # simulé en mode PAPER (position paper créée, aucun ordre broker)
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
