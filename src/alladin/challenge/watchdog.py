"""ChallengeWatchdog : suivi continu des règles de challenge, état du run, verdict.

Déterministe, sans I/O, sans LLM. Toute violation éliminatoire fait passer le run en FAILED :
cet état est terminal et irréversible (un nouveau run doit être créé).
"""

from __future__ import annotations

from datetime import datetime

from alladin.challenge import rules
from alladin.challenge.models import (
    ChallengeProfile,
    PhaseResult,
    RuleViolation,
    WatchdogEvent,
    WatchdogReport,
    WatchdogState,
)
from alladin.core.enums import TERMINAL_STATES, RuleSource, RunState
from alladin.core.errors import IrreversibleStateError
from alladin.core.models import AccountSnapshot

_ALLOWED = {
    RunState.CREATED: {RunState.READY, RunState.KILLED},
    RunState.READY: {RunState.RUNNING, RunState.PAUSED, RunState.KILLED},
    RunState.RUNNING: {
        RunState.TARGET_REACHED,
        RunState.PASSED,
        RunState.FAILED,
        RunState.PAUSED,
        RunState.KILLED,
    },
    RunState.TARGET_REACHED: {
        RunState.RUNNING,
        RunState.PASSED,
        RunState.FAILED,
        RunState.PAUSED,
        RunState.KILLED,
    },
    RunState.PAUSED: {RunState.RUNNING, RunState.FAILED, RunState.KILLED},
    RunState.PASSED: set(),
    RunState.FAILED: set(),
    RunState.KILLED: set(),
}


class ChallengeWatchdog:
    def __init__(self, profile: ChallengeProfile, state: WatchdogState) -> None:
        self.profile = profile
        self.state = state

    # ------------------------------------------------------------------ construction

    @classmethod
    def create(cls, profile: ChallengeProfile, run_id: str, initial_balance: float) -> ChallengeWatchdog:
        return cls(
            profile,
            WatchdogState(
                run_id=run_id,
                baseline_balance=initial_balance,
                last_balance=initial_balance,
                last_equity=initial_balance,
                peak_equity=initial_balance,
                lowest_equity=initial_balance,
                day_start_balance=initial_balance,
                day_start_equity=initial_balance,
            ),
        )

    # ------------------------------------------------------------------ transitions

    @property
    def run_state(self) -> RunState:
        return self.state.run_state

    @property
    def phase_number(self) -> int:
        return self.state.phase_index + 1

    def _transition(self, new: RunState) -> None:
        cur = self.state.run_state
        if cur in TERMINAL_STATES:
            raise IrreversibleStateError(
                f"run {self.state.run_id} est {cur} : état terminal, créer un nouveau run"
            )
        if new not in _ALLOWED[cur]:
            raise IrreversibleStateError(f"transition interdite {cur} -> {new}")
        self.state.run_state = new

    def mark_ready(self, snapshot: AccountSnapshot, now: datetime) -> None:
        self._transition(RunState.READY)
        self._sync_snapshot(snapshot, now, new_day_ok=True)

    def start(self, snapshot: AccountSnapshot, now: datetime) -> None:
        if self.state.run_state is RunState.CREATED:
            self.mark_ready(snapshot, now)
        self._transition(RunState.RUNNING)
        if self.state.phase_started_at is None:
            self.state.phase_started_at = now

    def pause(self) -> None:
        self._transition(RunState.PAUSED)

    def resume(self) -> None:
        self._transition(RunState.RUNNING)

    def kill(self) -> None:
        self._transition(RunState.KILLED)

    # ------------------------------------------------------------------ enregistrement d'activité

    def record_trade_opened(self, now: datetime) -> None:
        self._mark_trading_day(rules.day_key(now, self.profile.official_rules))

    def record_closed_pnl(self, pnl: float, closed_at: datetime) -> None:
        """P&L réalisé net (profit + commission + swap) d'un trade clôturé, attribué à son jour de clôture."""
        key = rules.day_key(closed_at, self.profile.official_rules)
        self.state.daily_closed_pnl[key] = self.state.daily_closed_pnl.get(key, 0.0) + pnl
        self._mark_trading_day(key)

    def _mark_trading_day(self, key: str) -> None:
        if key not in self.state.trading_days:
            self.state.trading_days.append(key)

    # ------------------------------------------------------------------ cœur : update

    def update(self, snapshot: AccountSnapshot, now: datetime, open_positions: int = 0) -> WatchdogReport:
        """Met à jour l'état depuis un snapshot réel du compte et évalue toutes les règles."""
        events: list[WatchdogEvent] = []
        st = self.state
        if st.run_state in TERMINAL_STATES or st.run_state in (RunState.CREATED, RunState.READY):
            self._sync_snapshot(snapshot, now, new_day_ok=st.run_state is not RunState.CREATED)
            return self._report(snapshot, now, events)

        self._sync_snapshot(snapshot, now, new_day_ok=True, events=events)
        off = self.profile.official_rules
        extra = self.profile.extra_rules
        floor_d = self._daily_floor()
        floor_t = rules.total_floor(off, st.baseline_balance)

        # 1. règles éliminatoires (officielles)
        if snapshot.equity <= floor_d:
            self._fail(
                RuleViolation(
                    rule="max_daily_loss",
                    source=RuleSource.OFFICIAL,
                    message=f"perte journalière maximale atteinte (equity {snapshot.equity:.2f} <= {floor_d:.2f})",
                    observed=snapshot.equity,
                    limit=floor_d,
                    at=now,
                ),
                events,
            )
        elif snapshot.equity <= floor_t:
            self._fail(
                RuleViolation(
                    rule="max_total_loss",
                    source=RuleSource.OFFICIAL,
                    message=f"perte totale maximale atteinte (equity {snapshot.equity:.2f} <= {floor_t:.2f})",
                    observed=snapshot.equity,
                    limit=floor_t,
                    at=now,
                ),
                events,
            )

        # 2. objectif / passage de phase
        if st.run_state in (RunState.RUNNING, RunState.TARGET_REACHED):
            self._evaluate_target(snapshot, now, open_positions, events)

        # 3. limite de durée (règle expérimentale ALLADIN)
        if st.run_state in (RunState.RUNNING, RunState.TARGET_REACHED, RunState.PAUSED) and (
            extra.max_days_per_phase is not None and st.phase_started_at is not None
        ):
            elapsed = (now - st.phase_started_at).total_seconds() / 86400
            if elapsed >= extra.max_days_per_phase:
                self._fail(
                    RuleViolation(
                        rule="max_days_per_phase",
                        source=RuleSource.EXTRA,
                        message=f"durée maximale de {extra.max_days_per_phase} jours dépassée sans validation de la phase",
                        observed=elapsed,
                        limit=float(extra.max_days_per_phase),
                        at=now,
                    ),
                    events,
                )

        # 4. blocage souple (règle ALLADIN, non éliminatoire)
        if (
            st.run_state not in TERMINAL_STATES
            and extra.soft_daily_loss_pct is not None
            and st.blocked_day != st.day_key
        ):
            soft_floor = (
                rules.daily_reference(off, st.day_start_balance, st.day_start_equity)
                - st.baseline_balance * extra.soft_daily_loss_pct / 100
            )
            if snapshot.equity <= soft_floor:
                st.blocked_day = st.day_key
                st.violations.append(
                    RuleViolation(
                        rule="soft_daily_loss",
                        source=RuleSource.EXTRA,
                        message=f"limite journalière ALLADIN {extra.soft_daily_loss_pct}% atteinte : nouveaux ordres bloqués jusqu'à demain",
                        observed=snapshot.equity,
                        limit=soft_floor,
                        fatal=False,
                        at=now,
                    )
                )
                events.append(WatchdogEvent(type="watchdog.soft_block", detail={"floor": soft_floor}))

        return self._report(snapshot, now, events)

    # ------------------------------------------------------------------ internes

    def _daily_floor(self) -> float:
        st = self.state
        return rules.daily_floor(
            self.profile.official_rules, st.baseline_balance, st.day_start_balance, st.day_start_equity
        )

    def _sync_snapshot(
        self,
        snap: AccountSnapshot,
        now: datetime,
        *,
        new_day_ok: bool,
        events: list[WatchdogEvent] | None = None,
    ) -> None:
        st = self.state
        key = rules.day_key(now, self.profile.official_rules)
        if st.day_key != key and new_day_ok:
            st.day_key = key
            st.day_start_balance = snap.balance
            st.day_start_equity = snap.equity
            if events is not None:
                events.append(
                    WatchdogEvent(
                        type="watchdog.new_day",
                        detail={"day": key, "start_balance": snap.balance, "start_equity": snap.equity},
                    )
                )
        if st.run_state not in TERMINAL_STATES:
            st.last_balance, st.last_equity = snap.balance, snap.equity
            st.peak_equity = max(st.peak_equity, snap.equity)
            st.lowest_equity = snap.equity if st.lowest_equity == 0 else min(st.lowest_equity, snap.equity)

    def _fail(self, violation: RuleViolation, events: list[WatchdogEvent]) -> None:
        st = self.state
        if st.run_state in TERMINAL_STATES:
            return
        st.violations.append(violation)
        st.run_state = RunState.FAILED
        st.close_positions_requested = self.profile.extra_rules.close_positions_on_fail
        events.append(
            WatchdogEvent(
                type="watchdog.run_failed",
                detail={
                    "rule": violation.rule,
                    "source": violation.source.value,
                    "message": violation.message,
                },
            )
        )

    def _evaluate_target(
        self, snap: AccountSnapshot, now: datetime, open_positions: int, events: list[WatchdogEvent]
    ) -> None:
        st = self.state
        off = self.profile.official_rules
        phase = self.profile.phases[st.phase_index]
        measure = snap.balance if off.target_measured_on == "balance" else snap.equity
        level = rules.target_level(st.baseline_balance, phase.profit_target_pct)

        if measure + 1e-6 < level:
            if st.run_state is RunState.TARGET_REACHED:
                st.run_state = RunState.RUNNING
                events.append(WatchdogEvent(type="watchdog.target_lost"))
            return

        if st.run_state is RunState.RUNNING:
            st.run_state = RunState.TARGET_REACHED
            events.append(WatchdogEvent(type="watchdog.target_reached", detail={"phase": self.phase_number}))

        unmet = self._pass_blockers(snap, open_positions)
        if unmet:
            return

        result = PhaseResult(
            phase=self.phase_number,
            name=phase.name,
            started_at=st.phase_started_at or now,
            passed_at=now,
            baseline_balance=st.baseline_balance,
            final_balance=snap.balance,
            profit_pct=(snap.balance - st.baseline_balance) / st.baseline_balance * 100,
            trading_days=len(st.trading_days),
        )
        st.phase_results.append(result)
        if st.phase_index + 1 >= len(self.profile.phases):
            st.run_state = RunState.PASSED
            events.append(WatchdogEvent(type="watchdog.run_passed", detail=result.model_dump(mode="json")))
            return
        # Phase suivante : nouvelle base de calcul = solde actuel, compteurs remis à zéro.
        st.phase_index += 1
        st.baseline_balance = snap.balance
        st.phase_started_at = now
        st.trading_days = []
        st.daily_closed_pnl = {}
        st.day_key = rules.day_key(now, off)
        st.day_start_balance, st.day_start_equity = snap.balance, snap.equity
        st.blocked_day = None
        st.run_state = RunState.RUNNING
        events.append(
            WatchdogEvent(
                type="watchdog.phase_passed",
                detail={**result.model_dump(mode="json"), "next_phase": self.phase_number},
            )
        )

    def _pass_blockers(self, snap: AccountSnapshot, open_positions: int) -> list[str]:
        st = self.state
        off = self.profile.official_rules
        extra = self.profile.extra_rules
        blockers: list[str] = []
        if len(st.trading_days) < off.min_trading_days:
            blockers.append(f"jours de trading insuffisants ({len(st.trading_days)}/{off.min_trading_days})")
        if extra.require_flat_to_pass and open_positions > 0:
            blockers.append("positions encore ouvertes")
        if extra.consistency.enabled:
            profit = snap.balance - st.baseline_balance
            share = rules.best_day_share_pct(st.daily_closed_pnl, profit)
            if share is not None and share > extra.consistency.max_best_day_share_pct:
                blockers.append(
                    f"consistency (règle ALLADIN) : best day {share:.1f}% > {extra.consistency.max_best_day_share_pct}%"
                )
        return blockers

    def _report(self, snap: AccountSnapshot, now: datetime, events: list[WatchdogEvent]) -> WatchdogReport:
        st = self.state
        off = self.profile.official_rules
        extra = self.profile.extra_rules
        phase = self.profile.phases[min(st.phase_index, len(self.profile.phases) - 1)]
        floor_d = self._daily_floor()
        floor_t = rules.total_floor(off, st.baseline_balance)
        daily_limit = rules.daily_loss_limit_amount(off, st.baseline_balance)
        total_limit = st.baseline_balance - floor_t
        daily_ref = rules.daily_reference(off, st.day_start_balance, st.day_start_equity)
        measure = snap.balance if off.target_measured_on == "balance" else snap.equity
        profit_total = snap.balance - st.baseline_balance
        elapsed = (now - st.phase_started_at).total_seconds() / 86400 if st.phase_started_at else 0.0

        reasons: list[str] = []
        if st.run_state not in (RunState.RUNNING, RunState.TARGET_REACHED):
            reasons.append(f"run {st.run_state.value} : aucun nouvel ordre")
        if st.blocked_day is not None and st.blocked_day == st.day_key:
            reasons.append("blocage journalier ALLADIN actif")
        if snap.equity <= floor_d or snap.equity <= floor_t:
            reasons.append("limite éliminatoire atteinte")

        return WatchdogReport(
            run_id=st.run_id,
            run_state=st.run_state,
            phase_number=self.phase_number,
            phase_name=phase.name,
            baseline_balance=st.baseline_balance,
            balance=snap.balance,
            equity=snap.equity,
            floating_pnl=snap.floating_pnl,
            target_pct=phase.profit_target_pct,
            target_level=rules.target_level(st.baseline_balance, phase.profit_target_pct),
            profit_pct=(measure - st.baseline_balance) / st.baseline_balance * 100,
            daily_floor=floor_d,
            daily_headroom=snap.equity - floor_d,
            daily_loss_used_pct=max(0.0, (daily_ref - snap.equity) / daily_limit * 100)
            if daily_limit
            else 0.0,
            total_floor=floor_t,
            total_headroom=snap.equity - floor_t,
            total_loss_used_pct=max(0.0, (st.baseline_balance - snap.equity) / total_limit * 100)
            if total_limit
            else 0.0,
            trading_days=len(st.trading_days),
            min_trading_days=off.min_trading_days,
            best_day_profit=rules.best_day_profit(st.daily_closed_pnl),
            best_day_share_pct=rules.best_day_share_pct(st.daily_closed_pnl, profit_total),
            days_elapsed=elapsed,
            max_days=extra.max_days_per_phase,
            can_open_new_positions=not reasons,
            blocked_reasons=reasons,
            violations=list(st.violations),
            events=events,
            close_positions_requested=st.close_positions_requested,
        )
