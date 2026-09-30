"""MockAgent : déterministe, sans LLM. Sert aux tests et au mode démo."""

from __future__ import annotations

from collections.abc import Sequence

from alladin.agents.base import AgentAdapter, AgentDecision, AgentIntentDraft, AgentRequest, AgentResponse
from alladin.core.enums import DecisionKind


class MockAgent(AgentAdapter):
    """Sans script : retient le meilleur signal de stratégie (confiance), sinon NO_TRADE.
    Avec `script` : rejoue des décisions prédéfinies (une par appel)."""

    name = "mock"

    def __init__(self, script: Sequence[AgentDecision] | None = None) -> None:
        self._script = list(script) if script is not None else None
        self.calls: list[AgentRequest] = []

    def propose(self, request: AgentRequest) -> AgentResponse:
        self.calls.append(request)
        if self._script is not None:
            decision = (
                self._script.pop(0)
                if self._script
                else AgentDecision(decision=DecisionKind.NO_TRADE, reason="script épuisé")
            )
            return AgentResponse(agent=self.name, decision=decision)
        signals = request.context.get("signals", [])
        if not signals:
            return AgentResponse(
                agent=self.name,
                decision=AgentDecision(
                    decision=DecisionKind.NO_TRADE, reason="aucun signal de stratégie sur la shortlist"
                ),
            )
        best = max(signals, key=lambda s: s["draft"]["confidence"])
        draft = AgentIntentDraft.model_validate(best["draft"])
        return AgentResponse(
            agent=self.name,
            decision=AgentDecision(
                decision=DecisionKind.TRADE,
                reason=f"meilleur signal : {draft.strategy_id} sur {draft.instrument}",
                intent=draft,
            ),
        )
