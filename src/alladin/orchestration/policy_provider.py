"""Opt-in context assembly from persisted simulation dossiers and causal archives.

No network, account lookup, broker execution or risk sizing. Snapshot collectors
and common-currency risk estimates must be explicitly injected by the caller.
"""

from __future__ import annotations

from collections.abc import Callable

from alladin.brain import Action, ActionProposal
from alladin.challenge.account_policy import AccountPolicyState, ExposureSnapshot, MarketSchedule
from alladin.challenge.calendar_composite import compose_calendar
from alladin.challenge.policy_archive import PolicyArchive
from alladin.challenge.policy_gate import PolicyContext
from alladin.challenge.policy_serialization import evidence_sha256
from alladin.core.enums import RunMode, Side
from alladin.core.workspace import AccountBinding


class ArchivedPolicyProvider:
    def __init__(
        self,
        *,
        archive: PolicyArchive,
        binding: AccountBinding,
        program: str,
        phase: str,
        mode: RunMode,
        open_positions: Callable[[ActionProposal], int],
        account_state: Callable[[ActionProposal], AccountPolicyState | None] = lambda _: None,
        exposures: Callable[[ActionProposal], ExposureSnapshot | None] = lambda _: None,
        market_schedule: Callable[[ActionProposal], MarketSchedule | None] = lambda _: None,
        proposed_risk: Callable[[ActionProposal], float | None] = lambda _: None,
        exposure_group: Callable[[ActionProposal], str | None] = lambda _: None,
    ) -> None:
        if mode not in {RunMode.OBSERVE, RunMode.PAPER} or not program.strip() or not phase.strip():
            raise ValueError("explicit OBSERVE/PAPER program and phase required")
        self.archive, self.binding, self.program, self.phase, self.mode = (
            archive,
            binding,
            program,
            phase,
            mode,
        )
        self.open_positions = open_positions
        self.account_state, self.exposures = account_state, exposures
        self.market_schedule, self.proposed_risk, self.exposure_group = (
            market_schedule,
            proposed_risk,
            exposure_group,
        )

    def __call__(self, proposal: ActionProposal) -> PolicyContext:
        if proposal.symbol is None:
            raise ValueError("market proposal required")
        dossier = self.archive.resolve_dossier(
            binding=self.binding,
            program=self.program,
            phase=self.phase,
            mode=self.mode,
            now=proposal.timestamp,
        )
        composite = compose_calendar(
            self.archive.calendars(now=proposal.timestamp),
            plan=dossier.coverage_plan,
            symbol=proposal.symbol,
            now=proposal.timestamp,
        )
        return PolicyContext(
            now=proposal.timestamp,
            symbol=proposal.symbol,
            open_positions=self.open_positions(proposal),
            firm_profile=dossier.profile,
            calendar=composite.snapshot,
            restrict_news=dossier.profile.restrict_news,
            account_state=self.account_state(proposal),
            exposures=self.exposures(proposal),
            market_schedule=self.market_schedule(proposal),
            proposed_risk_amount=self.proposed_risk(proposal),
            exposure_group=self.exposure_group(proposal),
            proposed_side={Action.LONG: Side.BUY, Action.SHORT: Side.SELL}.get(proposal.action),
            dossier_id=dossier.id,
            dossier_sha256=evidence_sha256(dossier),
            calendar_gaps=composite.gaps,
            calendar_batch_sha256=composite.batch_sha256,
        )
