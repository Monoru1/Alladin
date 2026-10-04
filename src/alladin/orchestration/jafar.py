"""Jafar mode policy and OBSERVE brain. No trading strategy is inherited."""

from pydantic import BaseModel, ConfigDict

from alladin.brain import Action, ActionProposal, BrainContext, proposal_identity
from alladin.core.enums import JafarMode
from alladin.core.errors import AlladinError
from alladin.journal.models import EventType
from alladin.journal.service import JournalService

_MODE_TRANSITIONS: dict[JafarMode, frozenset[JafarMode]] = {
    JafarMode.OBSERVE: frozenset({JafarMode.PAPER}),
    JafarMode.PAPER: frozenset({JafarMode.OBSERVE, JafarMode.TESTNET}),
    JafarMode.TESTNET: frozenset({JafarMode.OBSERVE, JafarMode.PAPER, JafarMode.LIVE_GATED}),
    JafarMode.LIVE_GATED: frozenset({JafarMode.OBSERVE, JafarMode.TESTNET, JafarMode.LIVE}),
    JafarMode.LIVE: frozenset({JafarMode.OBSERVE, JafarMode.LIVE_GATED}),
}


class JafarModeStore:
    """Etat de mode append-only, scoped au run et fail-closed au redemarrage."""

    def __init__(self, journal: JournalService, run_id: str) -> None:
        self.journal = journal
        self.run_id = run_id

    def load(self) -> JafarMode:
        events = self.journal.repo.events(self.run_id, [EventType.JAFAR_MODE_CHANGE])
        if not events:
            self.journal.log(
                self.run_id,
                EventType.JAFAR_MODE_CHANGE,
                {"from": None, "to": JafarMode.OBSERVE.value, "reason": "default_fail_closed"},
            )
            return JafarMode.OBSERVE
        try:
            return JafarMode(events[-1].payload["to"])
        except (KeyError, TypeError, ValueError) as exc:
            raise AlladinError("mode Jafar persiste invalide: reprise refusee") from exc

    def transition(self, target: JafarMode, *, reason: str) -> JafarMode:
        current = self.load()
        if target is current:
            return current
        if target not in _MODE_TRANSITIONS[current]:
            raise AlladinError(f"transition Jafar interdite: {current.value}->{target.value}")
        self.journal.log(
            self.run_id,
            EventType.JAFAR_MODE_CHANGE,
            {"from": current.value, "to": target.value, "reason": reason},
        )
        return target


class JafarExecutionReadiness(BaseModel):
    """Preuves necessaires a une future soumission exchange."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    risk_engine_passed: bool = False
    portfolio_risk_passed: bool = False
    reconciliation_ready: bool = False
    audit_ready: bool = False
    exchange_state_certain: bool = False
    key_trade_permission: bool = False
    withdrawals_disabled: bool = False
    explicit_live_authorization: bool = False


class JafarModeDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    mode: JafarMode
    exchange_submission_allowed: bool
    simulated_execution_allowed: bool
    reasons: tuple[str, ...]


def evaluate_jafar_mode(mode: JafarMode, readiness: JafarExecutionReadiness) -> JafarModeDecision:
    if mode is JafarMode.OBSERVE:
        return JafarModeDecision(
            mode=mode,
            exchange_submission_allowed=False,
            simulated_execution_allowed=False,
            reasons=("OBSERVE_NO_ORDERS",),
        )
    if mode is JafarMode.PAPER:
        return JafarModeDecision(
            mode=mode,
            exchange_submission_allowed=False,
            simulated_execution_allowed=True,
            reasons=("PAPER_SIMULATION_ONLY",),
        )
    if mode is JafarMode.LIVE_GATED:
        return JafarModeDecision(
            mode=mode,
            exchange_submission_allowed=False,
            simulated_execution_allowed=False,
            reasons=("LIVE_GATE_LOCKED",),
        )
    required = {
        "RISK_ENGINE_REQUIRED": readiness.risk_engine_passed,
        "PORTFOLIO_RISK_REQUIRED": readiness.portfolio_risk_passed,
        "RECONCILIATION_REQUIRED": readiness.reconciliation_ready,
        "AUDIT_REQUIRED": readiness.audit_ready,
        "EXCHANGE_STATE_UNCERTAIN": readiness.exchange_state_certain,
        "TRADE_PERMISSION_REQUIRED": readiness.key_trade_permission,
        "WITHDRAWALS_MUST_BE_DISABLED": readiness.withdrawals_disabled,
    }
    if mode is JafarMode.LIVE:
        required["EXPLICIT_LIVE_AUTHORIZATION_REQUIRED"] = readiness.explicit_live_authorization
    reasons = tuple(reason for reason, ready in required.items() if not ready)
    return JafarModeDecision(
        mode=mode, exchange_submission_allowed=not reasons, simulated_execution_allowed=False, reasons=reasons
    )


class JafarObserveBrain:
    source_id = "jafar:observe"
    source_version = "1"

    def decide(self, context: BrainContext) -> ActionProposal:
        return ActionProposal(
            proposal_id=proposal_identity(
                context.run_id, context.cycle_id, None, self.source_id, self.source_version
            ),
            run_id=context.run_id,
            cycle_id=context.cycle_id,
            source_id=self.source_id,
            source_version=self.source_version,
            timestamp=context.timestamp,
            action=Action.NO_TRADE,
            reasons=("Jafar skeleton: OBSERVE only, no strategy enabled",),
        )
