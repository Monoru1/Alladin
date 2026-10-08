"""Auditable quality evidence for offline policy probes, without execution rights."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from alladin.challenge.capital_metrics import CapitalLedger
from alladin.challenge.policy_gate import GateVerdict, PolicyContext, ProposedAction, evaluate_action

DATA_UNAVAILABLE_REASONS = frozenset({
    "CALENDAR_MISSING", "CALENDAR_STALE_OR_FUTURE", "CALENDAR_COVERAGE_INCOMPLETE",
    "POLICY_CONTEXT_UNAVAILABLE", "ACCOUNT_STATE_UNAVAILABLE", "ACCOUNT_STATE_MISMATCH",
    "EXPOSURE_UNAVAILABLE", "EXPOSURE_CURRENCY_MISMATCH", "PROPOSED_EXPOSURE_UNAVAILABLE",
    "PROPOSED_DIRECTION_UNAVAILABLE", "MARKET_SCHEDULE_UNAVAILABLE", "FIRM_PROFILE_MISSING",
    "FIRM_PROFILE_STALE", "CLOCK_UNTRUSTED", "INVALID_POSITION_CONTEXT",
    "NEWS_RULE_UNVERIFIED", "NEWS_RULE_PROFILE_MISMATCH",
})


@dataclass(frozen=True)
class PolicyProbe:
    probe_id: str
    account_ref: str
    action: ProposedAction
    context: PolicyContext
    expected_verdict: GateVerdict | None = None
    expected_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.probe_id.strip() or not self.account_ref.strip():
            raise ValueError("probe identity and opaque account reference required")
        if not isinstance(self.action, ProposedAction):
            raise ValueError("parsed action required")
        if self.expected_verdict is not None and not isinstance(self.expected_verdict, GateVerdict):
            raise ValueError("parsed expected verdict required")


def build_policy_quality_report(
    probes: tuple[PolicyProbe, ...], *, ledger: CapitalLedger | None = None,
) -> dict[str, Any]:
    """PASS means labelled policy expectations matched, never readiness or PnL.

    Missing economic measurements remain null, not zero. No risk approval, fill,
    operational availability or contractual certification is inferred here.
    """
    ids = [p.probe_id for p in probes]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate probe ids; do not double count restart evidence")
    verdicts: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    actions: Counter[str] = Counter()
    mismatches = 0
    labelled = 0
    records = []
    for probe in probes:
        context = probe.context
        decision = evaluate_action(probe.action, context)
        assessed = probe.expected_verdict is not None
        matches = (decision.verdict == probe.expected_verdict and (
            probe.expected_reason is None or decision.reason == probe.expected_reason)) if assessed else None
        labelled += int(assessed)
        mismatches += int(matches is False)
        verdicts[decision.verdict.value] += 1
        reasons[decision.reason] += 1
        actions[probe.action.value] += 1
        profile = context.firm_profile
        calendar = context.calendar
        records.append({
            "probe_id": probe.probe_id, "account_ref": probe.account_ref,
            "decision_at": context.now.isoformat(), "symbol": context.symbol,
            "action": probe.action.value, "verdict": decision.verdict.value,
            "reason": decision.reason, "event_ids": list(decision.event_ids),
            "expected_verdict": probe.expected_verdict.value if probe.expected_verdict is not None else None,
            "expected_reason": probe.expected_reason, "expectation_matches": matches,
            "profile": None if profile is None else {
                "firm": profile.firm, "program": profile.program, "phase": profile.phase,
                "account_type": profile.account_type, "version": profile.version,
                "constraints": profile.constraints.model_dump(mode="json") if profile.constraints else None,
                "source_url": profile.source_url, "verified_at": profile.verified_at.isoformat(),
                "valid_until": profile.valid_until.isoformat(), "restrict_news": profile.restrict_news,
            },
            "calendar": None if calendar is None else {
                "source": calendar.source, "as_of": calendar.as_of.isoformat(),
                "valid_until": calendar.valid_until.isoformat(),
                "coverage_complete": calendar.coverage_complete,
            },
        })
    status = "FAIL" if mismatches else ("PASS" if probes and labelled == len(probes) else "UNASSESSED")
    return {
        "schema_version": 1, "evidence_scope": "OFFLINE_POLICY_SIMULATION",
        "expectation_status": status, "runtime_integrated": False,
        "unattended_qualified": False, "execution_authorized": False,
        "samples": len(probes), "labelled_samples": labelled, "expectation_mismatches": mismatches,
        "verdict_counts": dict(sorted(verdicts.items())), "reason_counts": dict(sorted(reasons.items())),
        "action_counts": dict(sorted(actions.items())),
        "refused_decisions": sum(count for verdict, count in verdicts.items() if verdict != "ALLOW"),
        "data_unavailable_decisions": sum(count for reason, count in reasons.items() if reason in DATA_UNAVAILABLE_REASONS),
        "labelled_expectation_match_fraction": (labelled-mismatches)/labelled if labelled else None,
        "measurements": {"confirmed_fills": None, "net_trading_pnl": None, "max_drawdown": None,
                         "slippage": None, "availability": None, "recovery_seconds": None},
        "capital": None if ledger is None else {
            "simulated_allocation": ledger.simulated_allocation,
            "net_cash_generated": ledger.net_cash_generated,
            "payout_to_fee_ratio": ledger.payout_to_fee_ratio,
        },
        "limitations": ["No live calendar coverage or provider SLA certified",
                        "No real firm contract or account admission certified",
                        "No broker fills, protective exit review or risk approval",
                        "Account constraints may be tested separately; this report does not certify live scope",
                        "No MT5 DEMO, OOS performance or prolonged soak qualification"],
        "records": records,
    }
