"""Composition déterministe pré-exécution : décisions 032–035.

Ce module n'envoie aucun ordre. Il distingue entrée, sortie volontaire et
sortie protectrice sans prétendre pouvoir annuler un SL/TP déjà chez le broker.
Un branchement au runtime exige un audit des règles officielles du compte.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from alladin.challenge.account_policy import (
    AccountPolicyState,
    ExposureSnapshot,
    MarketSchedule,
    constraint_reason,
)
from alladin.challenge.event_policy import CalendarSnapshot, EventPolicy, EventVerdict
from alladin.challenge.firm_policy import FirmProfile, FirmVerdict, check_new_entry
from alladin.core.enums import Side


class ProposedAction(StrEnum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"
    PARTIAL_CLOSE = "PARTIAL_CLOSE"
    MODIFY_STOP = "MODIFY_STOP"
    MODIFY_TARGET = "MODIFY_TARGET"
    HOLD = "HOLD"


class GateVerdict(StrEnum):
    ALLOW = "ALLOW"
    DEFER = "DEFER"
    BLOCK = "BLOCK"
    REVIEW = "REVIEW"


@dataclass(frozen=True)
class PolicyContext:
    now: datetime
    symbol: str
    open_positions: int
    firm_profile: FirmProfile | None
    calendar: CalendarSnapshot | None
    restrict_news: bool | None
    account_state: AccountPolicyState | None = None
    market_schedule: MarketSchedule | None = None
    exposures: ExposureSnapshot | None = None
    proposed_risk_amount: float | None = None
    exposure_group: str | None = None
    proposed_side: Side | None = None
    protective: bool = False
    native_protection_active: bool = False


@dataclass(frozen=True)
class PolicyDecision:
    verdict: GateVerdict
    reason: str
    event_ids: tuple[str, ...] = ()


def evaluate_action(
    action: ProposedAction,
    context: PolicyContext,
    *,
    event_policy: EventPolicy | None = None,
) -> PolicyDecision:
    """Fail-closed on entries; escalate uncertain existing-position management.

    HOLD ne représente pas une transaction et ne requiert pas de flux calendrier.
    Une sortie protectrice d'urgence doit faire l'objet d'une procédure spécifique
    et ne saurait être bloquée par ce module isolé sans analyse du compte.
    """
    if not isinstance(action, ProposedAction):
        return PolicyDecision(GateVerdict.BLOCK, "UNKNOWN_ACTION")
    if action is ProposedAction.HOLD and not context.native_protection_active and (context.firm_profile is None or context.firm_profile.constraints is None):
        return PolicyDecision(GateVerdict.ALLOW, "NO_BROKER_TRANSACTION")
    is_entry = action is ProposedAction.OPEN
    if context.now.utcoffset() is None:
        return PolicyDecision(
            GateVerdict.BLOCK if is_entry else GateVerdict.REVIEW, "CLOCK_UNTRUSTED"
        )
    if not context.symbol.strip() or context.symbol != context.symbol.strip() or type(context.open_positions) is not int or context.open_positions < 0:
        return PolicyDecision(
            GateVerdict.BLOCK if is_entry else GateVerdict.REVIEW, "INVALID_POSITION_CONTEXT"
        )
    if context.firm_profile is None:
        return PolicyDecision(
            GateVerdict.BLOCK if is_entry else GateVerdict.REVIEW,
            "FIRM_PROFILE_MISSING",
        )
    if not context.firm_profile.verified_at <= context.now <= context.firm_profile.valid_until:
        return PolicyDecision(
            GateVerdict.BLOCK if is_entry else GateVerdict.REVIEW,
            "FIRM_PROFILE_STALE",
        )
    if not context.firm_profile.ea_allowed:
        return PolicyDecision(
            GateVerdict.BLOCK if is_entry else GateVerdict.REVIEW, "AUTOMATION_NOT_PERMITTED"
        )
    if context.firm_profile.constraints is not None:
        reason = constraint_reason(context.firm_profile.constraints, action=action.value,
            now=context.now, symbol=context.symbol, state=context.account_state,
            schedule=context.market_schedule, exposures=context.exposures,
            risk_amount=context.proposed_risk_amount, group=context.exposure_group, side=context.proposed_side)
        if reason:
            return PolicyDecision(GateVerdict.BLOCK if is_entry else GateVerdict.REVIEW, reason)
    if is_entry:
        firm = check_new_entry(
            context.firm_profile,
            now=context.now,
            symbol=context.symbol,
            open_positions=context.open_positions,
        )
        if firm.verdict is FirmVerdict.BLOCK:
            return PolicyDecision(GateVerdict.BLOCK, firm.reason)
    if context.restrict_news is not None and type(context.restrict_news) is not bool:
        return PolicyDecision(
            GateVerdict.BLOCK if is_entry else GateVerdict.REVIEW, "NEWS_RULE_UNVERIFIED"
        )
    if (context.firm_profile.restrict_news is not None
            and context.restrict_news != context.firm_profile.restrict_news):
        return PolicyDecision(
            GateVerdict.BLOCK if is_entry else GateVerdict.REVIEW, "NEWS_RULE_PROFILE_MISMATCH"
        )
    if context.restrict_news is None:
        return PolicyDecision(
            GateVerdict.BLOCK if is_entry else GateVerdict.REVIEW,
            "NEWS_RULE_UNVERIFIED",
        )
    news = (event_policy or EventPolicy()).evaluate(
        symbol=context.symbol,
        now=context.now,
        snapshot=context.calendar,
        restrict_news=context.restrict_news,
    )
    if news.verdict is EventVerdict.BLOCK:
        if news.reason in {"CALENDAR_MISSING", "CALENDAR_STALE_OR_FUTURE"}:
            return PolicyDecision(
                GateVerdict.BLOCK if is_entry else GateVerdict.REVIEW,
                news.reason,
            )
        if context.protective or (action is ProposedAction.HOLD and context.native_protection_active):
            return PolicyDecision(GateVerdict.REVIEW, "PROTECTIVE_NEWS_CONFLICT", news.event_ids)
        return PolicyDecision(GateVerdict.BLOCK, news.reason, news.event_ids)
    if action is ProposedAction.HOLD:
        return PolicyDecision(GateVerdict.ALLOW, "NO_BROKER_TRANSACTION")
    if news.verdict is EventVerdict.DEFER:
        if context.protective and action in {ProposedAction.CLOSE, ProposedAction.PARTIAL_CLOSE}:
            return PolicyDecision(GateVerdict.ALLOW, "PROTECTIVE_EXIT_CLEAR", news.event_ids)
        # Modification d'un SL/TP n'est pas une exécution garantie ; elle mérite
        # une revue de risque plutôt que d'être assimilée à un ordre d'entrée.
        if action in {ProposedAction.MODIFY_STOP, ProposedAction.MODIFY_TARGET}:
            return PolicyDecision(GateVerdict.REVIEW, news.reason, news.event_ids)
        return PolicyDecision(GateVerdict.DEFER, news.reason, news.event_ids)
    return PolicyDecision(GateVerdict.ALLOW, "POLICY_CLEAR")
