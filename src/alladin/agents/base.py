"""AgentAdapter : les LLM proposent/analysent, ils ne décident jamais de l'exécution.

Ce package n'importe NI les brokers NI le jeton d'approbation (vérifié par un test d'architecture) :
un agent n'a aucun moyen technique d'envoyer un ordre, ni d'accéder aux identifiants MT5.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from alladin.core.enums import DecisionKind, EntryType, MarketRegime, Side
from alladin.core.models import TradeIntent


class AgentIntentDraft(BaseModel):
    """Ce qu'un agent a le droit de proposer. PAS de volume, PAS de run_id, PAS d'expiration."""

    model_config = ConfigDict(extra="forbid")

    instrument: str
    side: Side
    strategy_id: str
    strategy_version: str
    market_regime: MarketRegime = MarketRegime.UNKNOWN
    entry_type: EntryType = EntryType.MARKET
    entry: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    requested_risk_pct_of_working_capital: float = Field(gt=0, le=100)
    confidence: float = Field(ge=0, le=1)
    reason: str = ""
    sources: list[str] = []

    def to_intent(
        self, *, run_id: str, agent: str, now: datetime, ttl: timedelta = timedelta(minutes=15)
    ) -> TradeIntent:
        """run_id, agent et expiration sont imposés par l'orchestrateur, jamais par l'agent."""
        return TradeIntent(
            run_id=run_id, agent=agent, expires_at=now + ttl, created_at=now, **self.model_dump()
        )


class AgentRequest(BaseModel):
    run_id: str
    context: dict[str, Any]  # shortlist, régimes, signaux de stratégies, enveloppe de risque. Aucun secret.


class AgentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: DecisionKind
    reason: str = ""
    intent: AgentIntentDraft | None = None


class AgentResponse(BaseModel):
    agent: str
    raw_text: str = ""
    decision: AgentDecision | None = None
    errors: list[str] = []
    duration_s: float = 0.0

    @property
    def ok(self) -> bool:
        return self.decision is not None and not self.errors


SYSTEM_PROMPT = (
    "Tu es un analyste de trading Forex dans un laboratoire d'expérimentation sur compte DEMO. "
    "Tu reçois une shortlist d'instruments, leur régime de marché et des signaux de stratégies versionnées. "
    "Tu proposes AU PLUS UN trade, ou NO_TRADE (décision parfaitement valide, souvent la meilleure). "
    "Tu ne choisis JAMAIS le volume : tu exprimes seulement requested_risk_pct_of_working_capital. "
    "Un moteur de risque déterministe valide, réduit ou refuse tout. Stop loss obligatoire. "
    "Réponds UNIQUEMENT par un objet JSON, sans texte autour, de la forme : "
    '{"decision":"TRADE"|"NO_TRADE","reason":"...","intent":{"instrument":"","side":"BUY|SELL","strategy_id":"",'
    '"strategy_version":"","market_regime":"","entry_type":"MARKET","entry":0.0,"stop_loss":0.0,"take_profit":0.0,'
    '"requested_risk_pct_of_working_capital":0.0,"confidence":0.0,"reason":"","sources":[]}} '
    "(intent = null si NO_TRADE). N'utilise aucun outil, n'exécute aucune commande."
)


def build_prompt(request: AgentRequest) -> str:
    return (
        f"{SYSTEM_PROMPT}\n\nCONTEXTE (JSON) :\n"
        f"{json.dumps(request.context, ensure_ascii=False, default=str, indent=1)}\n\nRéponds maintenant par le JSON."
    )


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Premier objet JSON équilibré dans `text` (tolère les clôtures ``` et le bavardage autour)."""
    candidates = [m.group(1) for m in _FENCE.finditer(text)] + [text]
    for cand in candidates:
        start = cand.find("{")
        while start != -1:
            depth, in_str, esc = 0, False, False
            for i in range(start, len(cand)):
                ch = cand[i]
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                elif ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            obj = json.loads(cand[start : i + 1])
                        except ValueError:
                            break
                        if isinstance(obj, dict):
                            return obj
                        break
            start = cand.find("{", start + 1)
    return None


def parse_agent_text(agent: str, text: str, duration_s: float = 0.0) -> AgentResponse:
    obj = extract_json_object(text)
    if obj is None:
        return AgentResponse(
            agent=agent,
            raw_text=text,
            errors=["aucun objet JSON exploitable dans la réponse"],
            duration_s=duration_s,
        )
    try:
        decision = AgentDecision.model_validate(obj)
    except ValidationError as exc:
        errs = [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]
        return AgentResponse(agent=agent, raw_text=text, errors=errs, duration_s=duration_s)
    if decision.decision is DecisionKind.TRADE and decision.intent is None:
        return AgentResponse(
            agent=agent, raw_text=text, errors=["decision=TRADE sans intent"], duration_s=duration_s
        )
    return AgentResponse(agent=agent, raw_text=text, decision=decision, duration_s=duration_s)


class AgentAdapter(ABC):
    name: str = "agent"

    @abstractmethod
    def propose(self, request: AgentRequest) -> AgentResponse: ...
