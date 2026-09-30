"""Cycle de vie des runs : création (RUN-001, RUN-002...), persistance, transitions, kill."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from alladin.challenge.models import ChallengeProfile, WatchdogReport, WatchdogState
from alladin.challenge.watchdog import ChallengeWatchdog
from alladin.core.enums import TERMINAL_STATES, RunState
from alladin.core.errors import AlladinError
from alladin.core.killswitch import KillSwitch
from alladin.core.models import AccountSnapshot
from alladin.journal.models import EventType, RunRecord
from alladin.journal.repository import JournalRepository
from alladin.journal.service import JournalService


@dataclass
class RunContext:
    run_id: str
    seq: int
    magic: int
    profile: ChallengeProfile
    watchdog: ChallengeWatchdog
    broker_name: str


def run_label(seq: int) -> str:
    return f"RUN-{seq:03d}"


class RunManager:
    def __init__(
        self,
        repo: JournalRepository,
        journal: JournalService,
        killswitch: KillSwitch,
        magic_base: int,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repo, self.journal, self.killswitch, self.magic_base = repo, journal, killswitch, magic_base
        self.clock = clock or (lambda: datetime.now(UTC))

    # ------------------------------------------------------------------ création / chargement

    def create_run(
        self, profile: ChallengeProfile, *, broker_name: str, account: str, initial_balance: float
    ) -> RunContext:
        seq = self.repo.next_run_seq()
        run_id = run_label(seq)
        wd = ChallengeWatchdog.create(profile, run_id, initial_balance)
        now = self.clock()
        self.repo.create_run(
            RunRecord(
                run_id=run_id,
                seq=seq,
                profile_id=profile.id,
                state=wd.run_state.value,
                phase=1,
                initial_balance=initial_balance,
                broker=broker_name,
                account=account,
                magic=self.magic_base + seq,
                created_at=now,
                updated_at=now,
                watchdog_state=wd.state.model_dump(mode="json"),
            )
        )
        self.journal.log(
            run_id,
            EventType.RUN_CREATED,
            {
                "profile": profile.model_dump(mode="json"),
                "initial_balance": initial_balance,
                "broker": broker_name,
                "account": account,
            },
        )
        return RunContext(run_id, seq, self.magic_base + seq, profile, wd, broker_name)

    def load_run(self, run_id: str, profile: ChallengeProfile) -> RunContext:
        rec = self.repo.get_run(run_id)
        if rec is None:
            raise AlladinError(f"run introuvable : {run_id}")
        wd = ChallengeWatchdog(profile, WatchdogState.model_validate(rec.watchdog_state))
        return RunContext(rec.run_id, rec.seq, rec.magic, profile, wd, rec.broker)

    def latest_run_id(self, *, only_open: bool = False) -> str | None:
        for rec in reversed(self.repo.list_runs()):
            if not only_open or RunState(rec.state) not in TERMINAL_STATES:
                return rec.run_id
        return None

    # ------------------------------------------------------------------ persistance

    def persist(self, ctx: RunContext) -> None:
        rec = self.repo.get_run(ctx.run_id)
        if rec is None or RunState(rec.state) in TERMINAL_STATES:
            return  # un run terminal n'est jamais réécrit
        self.repo.update_run(
            ctx.run_id,
            ctx.watchdog.run_state.value,
            ctx.watchdog.phase_number,
            ctx.watchdog.state.model_dump(mode="json"),
            self.clock(),
        )

    def _transition(self, ctx: RunContext, action: Callable[[], None], reason: str) -> None:
        before = ctx.watchdog.run_state
        action()
        self.persist(ctx)
        self.journal.log(
            ctx.run_id,
            EventType.RUN_STATE,
            {"from": before.value, "to": ctx.watchdog.run_state.value, "reason": reason},
        )

    def mark_ready(self, ctx: RunContext, snapshot: AccountSnapshot) -> None:
        self._transition(ctx, lambda: ctx.watchdog.mark_ready(snapshot, self.clock()), "broker vérifié")

    def start(self, ctx: RunContext, snapshot: AccountSnapshot) -> None:
        self._transition(ctx, lambda: ctx.watchdog.start(snapshot, self.clock()), "démarrage")

    def pause(self, ctx: RunContext, reason: str = "pause manuelle") -> None:
        self._transition(ctx, ctx.watchdog.pause, reason)

    def resume(self, ctx: RunContext) -> None:
        self._transition(ctx, ctx.watchdog.resume, "reprise manuelle")

    def kill(self, ctx: RunContext, reason: str) -> None:
        self.killswitch.activate(reason)
        self._transition(ctx, ctx.watchdog.kill, reason)
        self.journal.log(ctx.run_id, EventType.KILL_SWITCH, {"reason": reason})

    # ------------------------------------------------------------------ watchdog

    def sync_watchdog(
        self, ctx: RunContext, snapshot: AccountSnapshot, open_positions: int
    ) -> WatchdogReport:
        before = ctx.watchdog.run_state
        report = ctx.watchdog.update(snapshot, self.clock(), open_positions)
        for ev in report.events:
            self.journal.log(ctx.run_id, EventType.WATCHDOG, {"event": ev.type, **ev.detail})
        if ctx.watchdog.run_state is not before:
            self.journal.log(
                ctx.run_id,
                EventType.RUN_STATE,
                {"from": before.value, "to": ctx.watchdog.run_state.value, "reason": "watchdog"},
            )
        self.persist(ctx)
        return report
