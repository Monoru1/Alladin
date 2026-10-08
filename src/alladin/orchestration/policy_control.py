"""Opt-in policy checkpoint for OBSERVE/PAPER; no execution capability.

The provider is responsible for complete causal account/calendar/exposure inputs.
This checkpoint never supplies an execution token, sizing or a risk approval.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from alladin.brain import Action, ActionProposal, ProposalParameters, proposal_identity
from alladin.challenge.policy_gate import (
    GateVerdict,
    PolicyContext,
    PolicyDecision,
    ProposedAction,
    evaluate_action,
)
from alladin.challenge.policy_quality import DATA_UNAVAILABLE_REASONS
from alladin.challenge.policy_serialization import evidence_sha256
from alladin.core.enums import RunMode, Side
from alladin.core.workspace import AccountBinding
from alladin.journal.service import JournalService
from alladin.market.paper import PaperPosition
from alladin.orchestration.policy_provider import ArchivedPolicyProvider

ACTION_MAP = {Action.LONG: ProposedAction.OPEN, Action.SHORT: ProposedAction.OPEN,
              Action.CLOSE: ProposedAction.CLOSE, Action.PARTIAL_CLOSE: ProposedAction.PARTIAL_CLOSE,
              Action.MODIFY_STOP: ProposedAction.MODIFY_STOP, Action.MODIFY_TARGET: ProposedAction.MODIFY_TARGET,
              Action.HOLD: ProposedAction.HOLD}


def context_hash(context: PolicyContext) -> str:
    return evidence_sha256(context)


class PolicyController:
    def __init__(self, *, binding: AccountBinding,
                 context_provider: Callable[[ActionProposal], PolicyContext], journal: JournalService) -> None:
        self.binding = binding
        self.context_provider = context_provider
        self.journal = journal

    def assess(self, proposal: ActionProposal, mode: RunMode, *, _post_native_fill: bool = False) -> PolicyDecision:
        if mode not in {RunMode.OBSERVE, RunMode.PAPER}:
            raise ValueError("policy checkpoint only permits OBSERVE/PAPER")
        if _post_native_fill and (mode is not RunMode.PAPER or proposal.source_id != "policy-native-paper"):
            raise ValueError("native fill audit requires dedicated PAPER evidence")
        record = self.journal.repo.get_run(proposal.run_id)
        if record is None or record.account_binding != self.binding:
            raise ValueError("policy journal/run account binding mismatch")
        action = ACTION_MAP[proposal.action]
        context: PolicyContext | None = None
        error = None
        digest = None
        try:
            if isinstance(self.context_provider, ArchivedPolicyProvider) and (
                    self.context_provider.mode is not mode or self.context_provider.binding != self.binding):
                raise ValueError("archived provider mode/account mismatch")
            context = self.context_provider(proposal)
            if not isinstance(context, PolicyContext):
                context = None
                raise ValueError("policy provider returned invalid context")
            if _post_native_fill:
                context = replace(context, protective=True, native_protection_active=True)
            if context.now != proposal.timestamp or context.symbol != proposal.symbol:
                raise ValueError("policy/proposal snapshot identity mismatch")
            if (context.firm_profile and context.firm_profile.constraints
                    and context.firm_profile.constraints.account_ref != self.binding.account_ref):
                raise ValueError("policy/account binding mismatch")
            expected_side = {Action.LONG: Side.BUY, Action.SHORT: Side.SELL}.get(proposal.action)
            if expected_side is not None and context.proposed_side is not None and context.proposed_side is not expected_side:
                raise ValueError("policy/proposal direction mismatch")
            digest = context_hash(context)
            result = evaluate_action(action, context)
        except Exception as exc:
            error = type(exc).__name__  # no credential-bearing exception messages in the journal
            result = PolicyDecision(GateVerdict.BLOCK if action is ProposedAction.OPEN else GateVerdict.REVIEW,
                                    "POLICY_CONTEXT_UNAVAILABLE")
        profile = context.firm_profile if context else None
        calendar = context.calendar if context else None
        payload: dict[str, Any] = {
            "schema_version": 1, "proposal_id": proposal.proposal_id,
            "assessment_phase": "POST_NATIVE_PAPER_FILL" if _post_native_fill else "PRE_PROPOSAL",
            "proposal_sha256": hashlib.sha256(proposal.model_dump_json().encode()).hexdigest(),
            "action": action.value, "symbol": proposal.symbol, "mode": mode.value,
            "decision_at": proposal.timestamp.isoformat(), "verdict": result.verdict.value,
            "reason": result.reason, "event_ids": list(result.event_ids),
            "binding": self.binding.model_dump(mode="json"), "execution_authorized": False,
            "profile_version": profile.version if profile else None,
            "profile_source": profile.source_url if profile else None,
            "context_sha256": digest,
            "dossier_id": context.dossier_id if context else None,
            "dossier_sha256": context.dossier_sha256 if context else None,
            "calendar_gaps": list(context.calendar_gaps) if context else [],
            "calendar_batch_sha256": [list(pair) for pair in context.calendar_batch_sha256] if context else [],
            "calendar_source": calendar.source if calendar else None,
            "calendar_as_of": calendar.as_of.isoformat() if calendar else None,
            "calendar_valid_until": calendar.valid_until.isoformat() if calendar else None,
            "calendar_coverage_complete": calendar.coverage_complete if calendar else None,
            "provider_error": error,
        }
        # Stable proposal identity prevents repeat evidence after restart. A changed
        # proposal payload or different verdict under the same ID is an incident.
        existing = self.journal.repo.events(run_id=proposal.run_id, types=["policy.decision"])
        prior = next((e.payload for e in existing if e.payload.get("proposal_id") == proposal.proposal_id), None)
        if prior is not None:
            if json.dumps(prior, sort_keys=True) == json.dumps(payload, sort_keys=True):
                return result
            self.journal.log(proposal.run_id, "policy.incident", {
                "proposal_id": proposal.proposal_id, "reason": "POLICY_REPLAY_MISMATCH",
                "execution_authorized": False}, cycle_id=proposal.cycle_id)
            return PolicyDecision(GateVerdict.BLOCK if action is ProposedAction.OPEN else GateVerdict.REVIEW,
                                  "POLICY_REPLAY_MISMATCH")
        self.journal.log(proposal.run_id, "policy.decision", payload, cycle_id=proposal.cycle_id)
        return result


    def audit_native_exit(self, position: PaperPosition, cycle_id: str) -> PolicyDecision:
        """Post-fact simulated SL/TP evidence; never suppress a native protection."""
        if position.closed_at is None or position.status == "OPEN":
            raise ValueError("closed PAPER position required")
        opportunity = position.intent.get("opportunity_id") or f"NATIVE-{position.paper_id}"
        source = "policy-native-paper"
        proposal = ActionProposal(
            proposal_id=proposal_identity(position.run_id, cycle_id, opportunity, source),
            source_id=source, source_version="1", run_id=position.run_id, cycle_id=cycle_id,
            opportunity_id=opportunity, symbol=position.symbol, action=Action.CLOSE,
            timestamp=position.closed_at, parameters=ProposalParameters(position_id=position.paper_id),
            reasons=(position.status,),
        )
        result = self.assess(proposal, RunMode.PAPER, _post_native_fill=True)
        prior_incidents = self.journal.repo.events(position.run_id, types=["policy.incident"])
        already_logged = any(e.payload.get("proposal_id") == proposal.proposal_id
                             and e.payload.get("reason") == "NATIVE_PAPER_EXIT_REQUIRES_REVIEW" for e in prior_incidents)
        if result.verdict is not GateVerdict.ALLOW and not already_logged:
            self.journal.log(position.run_id, "policy.incident", {
                "proposal_id": proposal.proposal_id, "reason": "NATIVE_PAPER_EXIT_REQUIRES_REVIEW",
                "policy_reason": result.reason, "simulated_fill_observed": True,
                "event_ids": list(result.event_ids), "execution_authorized": False,
            }, cycle_id=cycle_id)
        return result


def policy_journal_report(journal: JournalService, run_id: str) -> dict[str, Any]:
    rows = journal.repo.events(run_id=run_id, types=["policy.decision", "policy.incident"])
    decisions = [row.payload for row in rows if row.type == "policy.decision"]
    incidents = [row.payload for row in rows if row.type == "policy.incident"]
    data_failures = sum(d.get("reason") in DATA_UNAVAILABLE_REASONS for d in decisions)
    ok, detail = journal.repo.verify_chain(run_id)
    return {"run_id": run_id, "scope": "POLICY_CHECKPOINT_OBSERVE_PAPER", "decisions": len(decisions),
            "verdict_counts": dict(Counter(str(d.get("verdict")) for d in decisions)),
            "reason_counts": dict(Counter(str(d.get("reason")) for d in decisions)),
            "refused_decisions": sum(d.get("verdict") in {"BLOCK", "DEFER", "REVIEW"}
                                     and d.get("assessment_phase") != "POST_NATIVE_PAPER_FILL" for d in decisions),
            "post_native_fill_assessments": sum(d.get("assessment_phase") == "POST_NATIVE_PAPER_FILL" for d in decisions),
            "native_fill_reviews": sum(d.get("assessment_phase") == "POST_NATIVE_PAPER_FILL"
                                       and d.get("verdict") != "ALLOW" for d in decisions),
            "data_unavailable_decisions": data_failures,
            "data_available_fraction": (len(decisions)-data_failures)/len(decisions) if decisions else None,
            "incidents": incidents, "journal_integrity": {"ok": ok, "detail": detail},
            "latest": decisions[-1] if decisions else None, "execution_authorized": False,
            "unattended_qualified": False, "wall_clock_availability": None}
